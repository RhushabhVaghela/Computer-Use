"""
Hybrid MCP server:
  - Exposes the existing computer-use MCP tools (from server.py) in this venv
  - Proxies browser DOM tools to browser-use MCP server running in a separate venv

Rationale:
  browser-use pins deps that conflict with open-interpreter, so it must live in its own venv.
  This server provides a single MCP endpoint that clients can connect to.
"""

import argparse
import asyncio
import builtins
import concurrent.futures
import io
import os
import sys
import threading
from typing import Any

import mcp.types as mcp_types
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


# ----------------------------
# stdout hygiene (stdio mode)
# ----------------------------
_orig_print = builtins.print


def safe_print(*args, **kwargs):
    # Default to stderr so we never corrupt JSON-RPC on stdout in stdio mode.
    if "file" not in kwargs or kwargs["file"] is None or kwargs["file"] == sys.stdout:
        kwargs["file"] = sys.stderr
    _orig_print(*args, **kwargs)


builtins.print = safe_print

class BrowserUseProxy:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._worker_thread: threading.Thread | None = None
        self._worker_ready = threading.Event()
        self._worker_loop: asyncio.AbstractEventLoop | None = None
        self._worker_stop: asyncio.Event | None = None
        self._worker_session: ClientSession | None = None
        self._errlog: io.TextIOBase | None = None
        self._debug = str(os.environ.get("HYBRID_DEBUG", "0")).strip().lower() in ("1", "true", "yes", "on")
        try:
            self._start_timeout_s = float(os.environ.get("HYBRID_BU_START_TIMEOUT_S", "25"))
        except Exception:
            self._start_timeout_s = 25.0
        try:
            self._call_timeout_s = float(os.environ.get("HYBRID_BU_CALL_TIMEOUT_S", "25"))
        except Exception:
            self._call_timeout_s = 25.0

    def _server_params(self) -> StdioServerParameters:
        # This file lives under <repo>/src. browser-use lives alongside the repo in the workspace root.
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        workspace_root = os.path.dirname(repo_root)
        bu_py = os.path.join(workspace_root, "browser-use", ".venv", "Scripts", "python.exe")
        if not os.path.exists(bu_py):
            # Allow override (e.g. different path/OS).
            bu_py = os.environ.get("BROWSER_USE_PYTHON", "") or sys.executable

        env = os.environ.copy()
        # Keep browser-use quiet; it can be very chatty.
        env.setdefault("BROWSER_USE_LOGGING_LEVEL", "warning")
        env.setdefault("BROWSER_USE_SETUP_LOGGING", "false")

        return StdioServerParameters(
            command=bu_py,
            args=["-m", "browser_use.mcp.server"],
            env=env,
        )

    def _open_errlog(self) -> io.TextIOBase:
        """
        IMPORTANT: When the hybrid server is itself run over stdio, the parent process might
        not continuously drain our stderr. If we forward browser-use stderr to our stderr,
        a chatty child process can fill the OS pipe buffer and deadlock tool calls.
        Default to NUL; allow opting into a file via HYBRID_BU_ERRLOG_PATH.
        """
        path = (os.environ.get("HYBRID_BU_ERRLOG_PATH", "") or "").strip()
        if path:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            except Exception:
                pass
            return open(path, "a", encoding="utf-8", errors="replace")
        return open(os.devnull, "w", encoding="utf-8", errors="ignore")

    def _thread_main(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._worker_loop = loop
        try:
            loop.run_until_complete(self._worker())
        finally:
            try:
                loop.stop()
            except Exception:
                pass
            try:
                loop.close()
            except Exception:
                pass

    async def _worker(self):
        # This runs in the background thread's event loop. We keep the browser-use MCP
        # subprocess and ClientSession alive here, and proxy requests via run_coroutine_threadsafe.
        self._worker_stop = asyncio.Event()
        params = self._server_params()
        if self._debug:
            print(f"[HYBRID]: (worker) starting browser-use MCP: {params.command} {' '.join(params.args)}", file=sys.stderr)

        if self._errlog is None:
            self._errlog = self._open_errlog()

        try:
            async with stdio_client(params, errlog=self._errlog) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._worker_session = session
                    self._worker_ready.set()
                    if self._debug:
                        print("[HYBRID]: (worker) browser-use session ready", file=sys.stderr)
                    await self._worker_stop.wait()
        finally:
            self._worker_session = None
            self._worker_ready.clear()
            if self._debug:
                print("[HYBRID]: (worker) stopped", file=sys.stderr)

    async def _wait_worker_ready(self):
        # Avoid blocking the server event loop on a sync Event.wait().
        await asyncio.to_thread(self._worker_ready.wait)

    def _submit(self, tool_name: str, arguments: dict[str, Any]) -> concurrent.futures.Future[list[mcp_types.Content]]:
        if self._worker_loop is None:
            raise RuntimeError("browser-use worker loop not started")
        return asyncio.run_coroutine_threadsafe(self._call_in_worker(tool_name, arguments), self._worker_loop)

    async def _call_in_worker(self, tool_name: str, arguments: dict[str, Any]) -> list[mcp_types.Content]:
        session = self._worker_session
        if session is None:
            raise RuntimeError("browser-use worker session not ready")
        res = await session.call_tool(tool_name, arguments)
        return list(res.content or [])

    async def ensure_started(self) -> ClientSession:
        # Fast path: already ready.
        async with self._lock:
            if self._worker_thread is not None and self._worker_ready.is_set():
                # Return value is unused by caller; we keep signature for minimal diffs.
                return self._worker_session  # type: ignore[return-value]
            needs_reset = self._worker_thread is not None or self._worker_loop is not None

        # Never call close() while holding the lock (close() also acquires it).
        if needs_reset:
            await self.close()

        async with self._lock:
            # Another caller may have started it while we were closing.
            if self._worker_thread is not None and self._worker_ready.is_set():
                return self._worker_session  # type: ignore[return-value]

            self._worker_ready.clear()
            self._worker_thread = threading.Thread(
                target=self._thread_main,
                name="browser-use-mcp-worker",
                daemon=True,
            )
            self._worker_thread.start()

        # Wait outside the lock so other calls can also wait without deadlocking.
        try:
            await asyncio.wait_for(self._wait_worker_ready(), timeout=self._start_timeout_s)
        except Exception:
            await self.close()
            raise
        return self._worker_session  # type: ignore[return-value]

    async def call(self, tool_name: str, arguments: dict[str, Any] | None = None):
        try:
            await self.ensure_started()
            if self._debug:
                print(f"[HYBRID]: bu call {tool_name}({arguments or {}})", file=sys.stderr)
            fut = self._submit(tool_name, arguments or {})
            res = await asyncio.wait_for(asyncio.wrap_future(fut), timeout=self._call_timeout_s)
            if self._debug:
                print(f"[HYBRID]: bu call done {tool_name}", file=sys.stderr)
            return res
        except Exception as e:
            # Reset on any failure so next call can retry cleanly.
            try:
                await self.close()
            except Exception:
                pass
            msg = f"[HYBRID ERROR]: browser-use proxy call failed: tool={tool_name} err={type(e).__name__}: {e}"
            try:
                return [mcp_types.TextContent(type="text", text=msg)]
            except Exception:
                return []

    async def close(self):
        async with self._lock:
            loop = self._worker_loop
            stop_evt = self._worker_stop
            thread = self._worker_thread
            self._worker_loop = None
            self._worker_stop = None
            self._worker_thread = None
            self._worker_session = None
            self._worker_ready.clear()

        # Signal stop outside the lock; joining can take time.
        if loop is not None and stop_evt is not None:
            try:
                loop.call_soon_threadsafe(stop_evt.set)
            except Exception:
                pass

        if thread is not None:
            try:
                await asyncio.to_thread(thread.join, timeout=5)
            except Exception:
                pass

        try:
            if self._errlog is not None:
                self._errlog.close()
        except Exception:
            pass
        self._errlog = None


bu_proxy = BrowserUseProxy()


def parse_args():
    p = argparse.ArgumentParser(description="Hybrid Computer-Use + Browser-Use MCP Server")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--stdio", action="store_true", help="Run in stdio mode")
    group.add_argument("--sse", action="store_true", help="Run in SSE mode")
    group.add_argument("--http", action="store_true", help="Run in Streamable HTTP mode")
    p.add_argument("--host", default="0.0.0.0", help="Bind address")
    p.add_argument("--port", type=int, default=8000, help="Port number")
    return p.parse_args()


def create_server(host: str, port: int) -> FastMCP:
    # Import computer-use server tools lazily so imports (pyautogui/UIA) happen in this venv.
    # NOTE: server.py applies a global monkeypatch to JSONRPC parsing for its own stdio mode.
    # That patch can interfere with the internal MCP client we use to talk to browser-use.
    # We don't need it here because we are not running server.py directly.
    _orig_validate = mcp_types.JSONRPCMessage.model_validate_json
    import server as cu
    mcp_types.JSONRPCMessage.model_validate_json = _orig_validate

    app = FastMCP(
        "Hybrid Computer-Use + Browser-Use",
        host=host,
        port=port,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        stateless_http=True,
    )

    # Expose computer-use tools unchanged.
    app.tool()(cu.computer)
    app.tool()(cu.read_screen_ui)
    app.tool()(cu.bash)
    app.tool()(cu.terminate_task)
    app.tool()(cu.rename_file)
    app.tool()(cu.update_thought)

    # Browser-use proxy tools (prefixed to avoid name collisions).
    @app.tool(description="(browser-use proxy) Navigate to a URL. Uses DOM automation via browser-use; prefer this over mouse when the browser is responsive.")
    async def bu_browser_navigate(url: str, new_tab: bool = False):
        return await bu_proxy.call("browser_navigate", {"url": url, "new_tab": new_tab})

    @app.tool(description="(browser-use proxy) Get current browser state (DOM snapshot, URL, etc). Optionally include a screenshot.")
    async def bu_browser_get_state(include_screenshot: bool = False):
        return await bu_proxy.call("browser_get_state", {"include_screenshot": include_screenshot})

    @app.tool(description="(browser-use proxy) Click an element by index or by page coordinates. Supports opening in a new tab.")
    async def bu_browser_click(index: int | None = None, coordinate_x: int | None = None, coordinate_y: int | None = None, new_tab: bool = False):
        args: dict[str, Any] = {"new_tab": new_tab}
        if index is not None:
            args["index"] = int(index)
        if coordinate_x is not None and coordinate_y is not None:
            args["coordinate_x"] = int(coordinate_x)
            args["coordinate_y"] = int(coordinate_y)
        return await bu_proxy.call("browser_click", args)

    @app.tool(description="(browser-use proxy) Type text into an input element specified by index.")
    async def bu_browser_type(index: int, text: str):
        return await bu_proxy.call("browser_type", {"index": int(index), "text": text})

    @app.tool(description="(browser-use proxy) Scroll the page up or down.")
    async def bu_browser_scroll(direction: str = "down"):
        d = (direction or "down").lower().strip()
        if d not in ("up", "down"):
            d = "down"
        return await bu_proxy.call("browser_scroll", {"direction": d})

    @app.tool(description="(browser-use proxy) Extract content from the current page using a query; optionally include links.")
    async def bu_browser_extract_content(query: str, extract_links: bool = False):
        return await bu_proxy.call("browser_extract_content", {"query": query, "extract_links": bool(extract_links)})

    @app.tool(description="(browser-use proxy) Navigate back in browser history.")
    async def bu_browser_go_back():
        return await bu_proxy.call("browser_go_back", {})

    @app.tool(description="(browser-use proxy) List open tabs in the current browser session.")
    async def bu_browser_list_tabs():
        return await bu_proxy.call("browser_list_tabs", {})

    @app.tool(description="(browser-use proxy) Switch to a specific tab by tab_id.")
    async def bu_browser_switch_tab(tab_id: str):
        return await bu_proxy.call("browser_switch_tab", {"tab_id": tab_id})

    @app.tool(description="(browser-use proxy) Close a specific tab by tab_id.")
    async def bu_browser_close_tab(tab_id: str):
        return await bu_proxy.call("browser_close_tab", {"tab_id": tab_id})

    @app.tool(description="(browser-use proxy) Run browser-use's agent loop for a task (multi-step DOM automation with retries).")
    async def bu_retry_with_browser_use_agent(task: str, max_steps: int = 100, model: str | None = None, allowed_domains: list[str] | None = None, use_vision: bool = True):
        args: dict[str, Any] = {"task": task, "max_steps": int(max_steps), "use_vision": bool(use_vision)}
        if model:
            args["model"] = model
        if allowed_domains is not None:
            args["allowed_domains"] = allowed_domains
        return await bu_proxy.call("retry_with_browser_use_agent", args)

    @app.tool(description="(browser-use proxy) List active browser sessions managed by browser-use.")
    async def bu_browser_list_sessions():
        return await bu_proxy.call("browser_list_sessions", {})

    @app.tool(description="(browser-use proxy) Close a specific browser session by session_id.")
    async def bu_browser_close_session(session_id: str):
        return await bu_proxy.call("browser_close_session", {"session_id": session_id})

    @app.tool(description="(browser-use proxy) Close all browser-use sessions and tabs.")
    async def bu_browser_close_all():
        return await bu_proxy.call("browser_close_all", {})

    return app


def main():
    args = parse_args()
    mcp = create_server(args.host, args.port)

    if args.stdio:
        mcp.run(transport="stdio")
    elif args.sse:
        mcp.run(transport="sse")
    elif args.http:
        import uvicorn

        app = mcp.streamable_http_app()
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
