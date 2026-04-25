"""
UI Element Detection using Windows UI Automation and Browser CDP.
Enumerates visible, interactive UI elements and returns them in a structured,
tree-like format inspired by browser-use.

Optimized for speed and intelligence:
- Filters out non-semantic containers.
- Groups children into compound components (e.g., Button with Text child).
- Extracts rich attributes (value, checked, etc.).
"""

import os
import sys
import platform
import json
import asyncio
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class UIElement:
    """A detected UI element with its properties."""
    index: int
    name: str
    control_type: str
    rect: tuple[int, int, int, int]  # (left, top, right, bottom)
    monitor_idx: int = 0
    is_interactive: bool = False
    children: List['UIElement'] = field(default_factory=list)
    attributes: Dict[str, str] = field(default_factory=dict)
    
    @property 
    def center(self) -> tuple[int, int]:
        """Center point in screen coordinates."""
        return (
            (self.rect[0] + self.rect[2]) // 2,
            (self.rect[1] + self.rect[3]) // 2,
        )
    
    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]
    
    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]


class UIElementProvider:
    """Detects and enumerates visible UI elements using OS accessibility APIs and Browser CDP."""
    
    # Semantic control types that should be shown to the model
    SEMANTIC_TYPES = {
        "Button", "Edit", "ComboBox", "CheckBox", "RadioButton", 
        "TabItem", "TreeItem", "Hyperlink", "ListItem", "MenuItem",
        "Window", "Document", "Pane", "Group", "Text", "Image", "Table", "Header",
        "Slider", "ProgressBar", "Spinner", "SplitButton", "Menu"
    }
    
    # Interactive types that get an index
    INTERACTIVE_TYPES = {
        "Button", "Edit", "ComboBox", "CheckBox", "RadioButton", 
        "Hyperlink", "ListItem", "MenuItem", "TabItem", "TreeItem",
        "Pane", "Group" # Added for better landmarking
    }
    
    # Containers that can be skipped if they don't have a name and have only one child
    COLLAPSIBLE_CONTAINERS = {"PaneControl", "GroupControl"} # Removed Pane/Group from here to allow them if they have names

    def __init__(self, monitor: dict | None = None):
        self._monitor = monitor
        self._elements_map: Dict[int, UIElement] = {}
        self._next_index = 1
        self._element_limit = 250
        self._max_depth = 5 # Reduced from 10 to instantly speed up OS scans
        self._browser_port = int(os.environ.get("BROWSER_CDP_PORT", "9222"))
    
    def reset(self):
        """Clear the detected elements cache."""
        self._elements_map = {}
        self._next_index = 1
    
    def scan(self, monitors: list[dict] = None) -> list[UIElement]:
        """Scan the screen using OS UI Automation."""
        self.reset()
        if platform.system() == "Windows":
            root_elements = self._scan_windows(monitors)
            # Flatten for easier lookup by index
            self._flatten_tree(root_elements)
            return root_elements
        return []

    def _get_browser_window_rect(self) -> Optional[tuple[int, int, int, int]]:
        """Find the active browser window rect using UIAutomation."""
        try:
            import uiautomation as auto
            active_win = auto.GetForegroundWindow()
            if not active_win:
                return None
            
            ctrl = auto.ControlFromHandle(active_win)
            name = (ctrl.Name or "").lower()
            # Common browser names
            if any(b in name for b in ["chrome", "edge", "brave", "firefox", "opera"]):
                # Try to find the document/pane that contains the web content
                # Chrome/Edge usually have a 'Document' control
                doc = ctrl.DocumentControl(searchDepth=3)
                if doc.Exists(0):
                    r = doc.BoundingRectangle
                    return (r.left, r.top, r.right, r.bottom)
                
                # Fallback to the whole window if no document found
                r = ctrl.BoundingRectangle
                return (r.left, r.top, r.right, r.bottom)
        except Exception:
            pass
        return None

    async def scan_browser(self) -> str:
        """Scan the active browser using Playwright/CDP."""
        try:
            from playwright.async_api import async_playwright
            
            # Find the browser window rect on the desktop for coordinate mapping
            win_rect = self._get_browser_window_rect()
            win_left = win_rect[0] if win_rect else 0
            win_top = win_rect[1] if win_rect else 0

            async with async_playwright() as p:
                # Try to connect to an existing browser instance
                browser = await p.chromium.connect_over_cdp(f"http://localhost:{self._browser_port}")
                context = browser.contexts[0] if browser.contexts else None
                if not context:
                    return "Error: No active browser context found on port " + str(self._browser_port)
                
                page = context.pages[0] if context.pages else await context.new_page()
                
                # USE A RAW STRING. Do NOT use an f-string to avoid { } conflicts with JS!
                js_script = """
                (function() {
                    const win_left = __WIN_LEFT__;
                    const win_top = __WIN_TOP__;
                    
                    const EVAL_KEY_ATTRIBUTES = [
                        'name', 'type', 'placeholder', 'aria-label', 'role', 'value',
                        'checked', 'selected', 'disabled', 'required', 'readonly',
                        'aria-expanded', 'aria-pressed', 'aria-checked', 'aria-selected',
                        'alt', 'title', 'data-testid', 'href', 'aria-haspopup'
                    ];

                    const INTERACTIVE_TAGS = new Set([
                        'a', 'button', 'input', 'select', 'textarea', 'details', 'summary'
                    ]);

                    const IGNORED_TAGS = new Set([
                        'script', 'style', 'head', 'meta', 'link', 'noscript'
                    ]);

                    let index = 1;

                    function isElementVisible(node) {
                        const rect = node.getBoundingClientRect();
                        if (rect.width <= 0 || rect.height <= 0) return false;
                        const style = window.getComputedStyle(node);
                        if (style.visibility === 'hidden' || style.display === 'none' || parseFloat(style.opacity) === 0) return false;
                        return true;
                    }

                    function isInteractive(node) {
                        const tag = node.tagName.toLowerCase();
                        if (INTERACTIVE_TAGS.has(tag)) return true;
                        
                        if (node.hasAttribute('onclick') || 
                            node.getAttribute('role') === 'button' || 
                            node.getAttribute('role') === 'link' ||
                            node.getAttribute('role') === 'checkbox' ||
                            node.getAttribute('role') === 'menuitem') return true;
                            
                        const style = window.getComputedStyle(node);
                        if (style.cursor === 'pointer') return true;
                        
                        return false;
                    }

                    function getSelectOptions(node) {
                        if (node.tagName.toLowerCase() !== 'select') return null;
                        const options = Array.from(node.options);
                        if (options.length === 0) return null;
                        
                        const firstOptions = options.slice(0, 5).map(opt => opt.text.trim() || opt.value);
                        return {
                            count: options.length,
                            first_options: firstOptions,
                            selected: node.selectedIndex >= 0 ? options[node.selectedIndex].text : null
                        };
                    }

                    function serialize(node, depth = 0) {
                        if (node.nodeType !== Node.ELEMENT_NODE) return null;
                        
                        const tag = node.tagName.toLowerCase();
                        if (IGNORED_TAGS.has(tag)) return null;

                        const isVisible = isElementVisible(node);
                        const interactive = isInteractive(node);
                        
                        const children = [];
                        for (const child of node.childNodes) {
                            const serializedChild = serialize(child, depth + 1);
                            if (serializedChild) children.push(serializedChild);
                        }

                        // Collect attributes
                        const attrs = {};
                        for (const attr of EVAL_KEY_ATTRIBUTES) {
                            if (node.hasAttribute(attr)) attrs[attr] = node.getAttribute(attr);
                        }

                        // Get text content
                        let text = "";
                        for(const child of node.childNodes) {
                            if(child.nodeType === Node.TEXT_NODE && child.textContent.trim()) {
                                text += child.textContent.trim() + " ";
                            }
                        }
                        text = text.trim();

                        // Compound component for select
                        const selectInfo = getSelectOptions(node);
                        if (selectInfo) {
                            attrs['options_count'] = selectInfo.count;
                            attrs['options'] = selectInfo.first_options.join('|');
                            if (selectInfo.selected) attrs['selected_text'] = selectInfo.selected;
                        }

                        // Filtering:
                        if (!isVisible && children.length === 0) return null;
                        
                        const isGeneric = ['div', 'span', 'section', 'article', 'p'].includes(tag);
                        if (isGeneric && Object.keys(attrs).length === 0 && !text && children.length === 1 && !interactive) {
                            return children[0];
                        }
                        
                        if (!interactive && !text && children.length === 0 && Object.keys(attrs).length === 0) {
                            return null;
                        }

                        const rect = node.getBoundingClientRect();
                        return {
                            tag,
                            idx: interactive ? index++ : null,
                            text: text.substring(0, 100),
                            attrs,
                            center: { x: Math.round(rect.left + rect.width/2 + win_left), y: Math.round(rect.top + rect.height/2 + win_top) },
                            children: children.length > 0 ? children : undefined
                        };
                    }

                    function formatTree(node, depth = 0) {
                        if (!node) return "";
                        const indent = "  ".repeat(depth);
                        const idxStr = node.idx ? `[${node.idx}] ` : "";
                        
                        let attrStr = "";
                        for (const [k, v] of Object.entries(node.attrs)) {
                            attrStr += ` ${k}="${v}"`;
                        }
                        
                        let line = `[M1] ${indent}${idxStr}<${node.tag}${attrStr}`;
                        if (node.text) line += ` text="${node.text}"`;
                        line += ` at (${node.center.x},${node.center.y})`;
                        
                        if (!node.children || node.children.length === 0) {
                            return line + " />";
                        }
                        
                        let childrenStr = node.children.map(c => formatTree(c, depth + 1)).filter(s => s).join("\\n");
                        if (!childrenStr) return line + " />";
                        
                        return `${line}>\\n${childrenStr}\\n${indent}</${node.tag}>`;
                    }

                    const tree = serialize(document.body);
                    return formatTree(tree);
                })()
                """.replace("__WIN_LEFT__", str(win_left)).replace("__WIN_TOP__", str(win_top))
                
                result = await page.evaluate(js_script)
                await browser.close()
                return result
        except Exception as e:
            return f"Error connecting to browser: {str(e)}. Make sure to launch with --remote-debugging-port={self._browser_port}"

    def get_element(self, index: int) -> UIElement | None:
        """Get element by its index number."""
        return self._elements_map.get(index)
    
    def format_for_llm(
        self,
        monitors: list[dict],
        computer_tool=None,
        max_elements: int = 150,
        desktop: dict | None = None,
        display_size: tuple[int, int] | None = None,
        elements: List[UIElement] | None = None
    ) -> str:
        """Format element tree as a rich, indented structure for the LLM."""
        root_elements = elements if elements is not None else self._scan_windows(monitors)
        if elements is None:
            self.reset()
            self._flatten_tree(root_elements)
        
        header = (
            "[UI TREE SNAPSHOT]\n"
            "The following is a hierarchical view of the screen. "
            "Use the index in brackets [idx] for the 'computer' tool. "
            "Hierarchical structure helps you understand context (e.g., labels near inputs).\n"
        )
        
        if not root_elements:
            return header + "[No UI elements detected]"
            
        tree_lines = []
        for el in root_elements:
            line = self._format_element_recursive(el, 0, desktop, display_size)
            if line:
                tree_lines.append(line)
            
        return header + "\n".join(tree_lines)

    def _format_element_recursive(self, el: UIElement, depth: int, desktop, display_size) -> str:
        indent = "  " * depth
        
        # Map center to screenshot pixels if needed
        cx, cy = el.center
        if desktop and display_size and desktop.get("width") and desktop.get("height"):
            dl, dt, dw, dh = desktop["left"], desktop["top"], desktop["width"], desktop["height"]
            out_w, out_h = display_size
            sx = round((cx - dl) * (out_w / dw))
            sy = round((cy - dt) * (out_h / dh))
            px, py = int(sx), int(sy)
        else:
            px, py = int(cx), int(cy)

        idx_str = f"[{el.index}] " if el.is_interactive else ""
        name_str = f"\"{el.name}\"" if el.name and el.name != f"<{el.control_type}>" else ""
        
        # Build attribute string
        attr_str = ""
        for k, v in el.attributes.items():
            attr_str += f" {k}=\"{v}\""

        line = f"[M{el.monitor_idx+1}] {indent}{idx_str}<{el.control_type}{attr_str}"
        if name_str: line += f" name={name_str}"
        line += f" at ({px},{py})"
        
        if not el.children:
            return line + " />"
            
        child_lines = []
        for child in el.children:
            child_line = self._format_element_recursive(child, depth + 1, desktop, display_size)
            if child_line:
                child_lines.append(child_line)
            
        if not child_lines:
            return line + " />"
            
        return f"{line}>\n" + "\n".join(child_lines) + f"\n{indent}</{el.control_type}>"

    def _flatten_tree(self, elements: List[UIElement]):
        """Populate self._elements_map for flat lookup."""
        for el in elements:
            if el.is_interactive:
                self._elements_map[el.index] = el
            self._flatten_tree(el.children)

    def _scan_windows(self, monitors: list[dict]) -> list[UIElement]:
        """Enumerate UI elements using Windows UI Automation in a hierarchical tree."""
        try:
            import uiautomation as auto
        except ImportError:
            return []
        
        if not monitors:
            return []

        mon_bounds = []
        for m in monitors:
            mon_bounds.append({
                "l": m["left"], "t": m["top"], 
                "r": m["left"] + m["width"], 
                "b": m["top"] + m["height"]
            })

        try:
            desktop_root = auto.GetRootControl()
            active_win_handle = auto.GetForegroundWindow()
            
            root_elements = []
            seen_handles = set()
            
            # 1. Process all top-level windows
            # 1. Process all top-level windows
            for win in desktop_root.GetChildren():
                try:
                    # Skip our own overlay
                    if win.Name == "ComputerUseOverlay":
                        continue
                    
                    # ENHANCEMENT: Skip completely invisible windows immediately
                    rect = win.BoundingRectangle
                    if not rect or rect.width() <= 0 or rect.height() <= 0:
                        continue
                        
                    # Determine if it's the active window for deep scanning
                    is_active = (win.NativeWindowHandle == active_win_handle)
                    
                    # Shallow scan background windows, deep scan active one
                    # THE SPEED HACK: 
                    # Depth 8 for the active app (fast for native apps, cuts off browser bloat).
                    # Depth 1 for background apps (just gets their window borders).
                    old_depth = self._max_depth
                    self._max_depth = 8 if is_active else 1
                    
                    root_el = self._process_node(win, mon_bounds, depth=0, seen_handles=seen_handles)
                    if root_el:
                        root_elements.append(root_el)
                    
                    self._max_depth = old_depth
                except Exception:
                    continue
            
            return root_elements
                
        except Exception:
            return []

    def _process_node(self, node, mon_bounds, depth, seen_handles) -> Optional[UIElement]:
        """Recursively process a UIA node and build a tree element."""
        if depth > self._max_depth:
            return None
        
        try:
            try:
                h = node.NativeWindowHandle
                if h and h in seen_handles: return None
                if h: seen_handles.add(h)
            except Exception: pass

            rect = node.BoundingRectangle
            if not rect or rect.width() <= 2 or rect.height() <= 2:
                return None
            
            mid_x, mid_y = (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
            monitor_idx = -1
            for i, mb in enumerate(mon_bounds):
                if mb["l"] <= mid_x < mb["r"] and mb["t"] <= mid_y < mb["b"]:
                    monitor_idx = i
                    break
            if monitor_idx == -1: return None

            ct = node.ControlTypeName.replace("Control", "")
            name = node.Name or ""
            
            # Interactive check
            is_interactive = ct in self.INTERACTIVE_TYPES
            
            # Extract attributes early for semantic decisions
            attrs = {}
            try:
                if ct == "Edit":
                    try:
                        val = node.GetValuePattern().Value
                        if val: attrs["value"] = val[:50]
                    except Exception: pass
                    # Check for placeholder in HelpText
                    if not name and node.HelpText:
                        attrs["placeholder"] = node.HelpText[:50]
                
                if ct in {"CheckBox", "RadioButton"}:
                    try:
                        attrs["checked"] = str(node.GetTogglePattern().ToggleState == 1).lower()
                    except Exception: pass

                if ct == "ComboBox":
                    try:
                        # Try to get the selected item value
                        val = node.GetValuePattern().Value
                        if val: attrs["selected"] = val[:50]
                    except Exception: pass

                if ct == "Slider":
                    try:
                        val = node.GetRangeValuePattern().Value
                        attrs["value"] = str(val)
                    except Exception: pass
            except Exception: pass

            # Recursively process children
            children = []
            for child in node.GetChildren():
                child_el = self._process_node(child, mon_bounds, depth + 1, seen_handles)
                if child_el:
                    children.append(child_el)

            # Optimization: Grouping child text into parent for interactive elements
            # If a Button has only one child and it's Text, use its name and drop the child
            if is_interactive and not name and len(children) == 1 and children[0].control_type == "Text":
                name = children[0].name
                children = []

            # Optimization: If interactive and has multiple children that are just Text/Image, 
            # concatenate their names into the parent's name.
            if is_interactive and not name and children:
                all_text_names = []
                non_text_children = []
                for c in children:
                    if c.control_type in ("Text", "Image") and c.name:
                        all_text_names.append(c.name)
                    else:
                        non_text_children.append(c)
                
                if all_text_names and not non_text_children:
                    name = " ".join(all_text_names).strip()
                    children = []

            # Optimization: Collapse container if redundant
            # If it's a Pane/Group with no name and only one child, return the child
            if ct in self.COLLAPSIBLE_CONTAINERS and not name and len(children) == 1:
                return children[0]
            
            # Skip non-semantic elements that have no name and no children
            is_semantic = ct in self.SEMANTIC_TYPES
            if not is_semantic and not name and not children:
                return None

            idx = 0
            if is_interactive:
                idx = self._next_index
                self._next_index += 1

            return UIElement(
                index=idx,
                name=name[:100],
                control_type=ct,
                rect=(rect.left, rect.top, rect.right, rect.bottom),
                monitor_idx=monitor_idx,
                is_interactive=is_interactive,
                children=children,
                attributes=attrs
            )
            
        except Exception:
            return None
