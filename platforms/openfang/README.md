# OpenFang + Open Interpreter Integration

This directory contains the legacy installation scripts, Dockerfiles, and patches specifically designed for **OpenFang**.

It preserves the exact logic from the old `openfang-interpreter-bridge` repository.

## Contents
- **`bridge.ps1`**: Master Windows installer that creates condoms, installs packages, patches OpenFang desktop, and auto-injects the MCP TOML config.
- **`bridge.sh`**: Unix equivalent and Docker entrypoint for starting NoVNC + OpenFang.
- **`Dockerfile` / `docker-compose.yml`**: Containerized deployment for OpenFang with a secure VNC desktop.
- **`openfang_isolation_utf8.patch`**: Custom patch applied to OpenFang desktop for utf8 isolation.
- **`open_interpreter_init.patch`**: Specific patch for init stability.
- **`openfang-hands/`**: Default hands directory for OpenFang isolation.

## Usage

If you already have OpenFang installed, you **don't need these scripts**. You can just point your `config.toml` to the universal server:

```toml
[mcp_servers.computer-use]
command = "python"
args = ["d:/Agents-and-other-repos/oi-computer-use-mcp/server.py", "--stdio"]
```

Hybrid mode (adds `bu_*` browser DOM tools via `browser-use` proxy):

```toml
[mcp_servers.computer-use-hybrid]
command = "python"
args = ["d:/Agents-and-other-repos/oi-computer-use-mcp/hybrid_server.py", "--stdio"]
```

However, if you want the **fully automated Windows/Docker installation**, run:

```bash
# Windows
.\bridge.ps1 install

# Docker
docker-compose up -d
```
