"""
Overlay renderer for oi-computer-use-mcp.

Why this exists:
  - Tk's `-transparentcolor` (color-key) transparency cannot preserve anti-aliased edges.
    It makes rounded rectangles / shadows look pixelated on Windows.
  - Windows layered windows (UpdateLayeredWindow + per-pixel alpha) render smoothly.

This module provides `MouseOverlay`, which is used by `server.py`.
The class is intentionally thread-safe and "best effort" (never crash the MCP server).
"""

from __future__ import annotations

import ctypes
import math
import os
import queue
import sys
import threading
import time
import traceback
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


def _clamp_int(v) -> int:
    try:
        return int(v)
    except Exception:
        return 0


def _get_cursor_pos():
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)) == 0:
            return None
        return int(pt.x), int(pt.y)
    except Exception:
        return None


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    import win32con
    import win32gui

    _GDI32 = ctypes.WinDLL("gdi32", use_last_error=True)

    # ctypes defaults many args to 32-bit c_int, which breaks on 64-bit handles.
    # Define signatures for the functions we use.
    _HGDIOBJ = wintypes.HANDLE
    _HBITMAP = wintypes.HANDLE

    _GDI32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _GDI32.CreateCompatibleDC.restype = wintypes.HDC
    _GDI32.DeleteDC.argtypes = [wintypes.HDC]
    _GDI32.DeleteDC.restype = wintypes.BOOL
    _GDI32.SelectObject.argtypes = [wintypes.HDC, _HGDIOBJ]
    _GDI32.SelectObject.restype = _HGDIOBJ
    _GDI32.DeleteObject.argtypes = [_HGDIOBJ]
    _GDI32.DeleteObject.restype = wintypes.BOOL

    class _BLENDFUNCTION(ctypes.Structure):
        _fields_ = [
            ("BlendOp", wintypes.BYTE),
            ("BlendFlags", wintypes.BYTE),
            ("SourceConstantAlpha", wintypes.BYTE),
            ("AlphaFormat", wintypes.BYTE),
        ]

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class _BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    # CreateDIBSection signature
    _GDI32.CreateDIBSection.argtypes = [
        wintypes.HDC,
        ctypes.POINTER(_BITMAPINFO),
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    _GDI32.CreateDIBSection.restype = _HBITMAP


@dataclass
class _LayeredSurface:
    hwnd: int
    hdc_mem: int
    hbmp: int
    hbmp_old: int
    bits_ptr: ctypes.c_void_p
    w: int
    h: int


class MouseOverlay:
    """
    Per-pixel-alpha overlay (Windows only).

    Public API is kept compatible with the old implementation used by `server.py`:
      - show(x, y, text)
      - update_label(text)
      - status(text, color)
      - hide()
      - move(x, y)
      - stop()
    """

    def __init__(self):
        self.queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.running = True

        # Coalesce cursor moves (server can push many during smooth motion).
        self._cursor_lock = threading.Lock()
        self._pending_cursor: tuple[int, int] | None = None
        self._last_cursor: tuple[int, int] | None = None
        self._visible = False

        # Layout / visuals
        self._offset_x = 16
        self._offset_y = -34
        self._ss = 2
        self._ring_size = 56

        # Transition / state
        self._last_text_set_at = 0.0
        self._pending_text: tuple[str, str] | None = None
        self._fade_started_at = 0.0
        self._pulse_enabled = False
        self._requested_status_color = "yellow"

        self._current_action = ""
        self._current_thinking = ""

        # Fonts (PIL ImageFont)
        self._font_action = None
        self._font_thinking = None

        # Win32 resources (overlay thread only)
        self._hwnd_pill: int | None = None
        self._hwnd_ring: int | None = None
        self._hdc_screen: int | None = None
        self._surf_pill: _LayeredSurface | None = None
        self._surf_ring: _LayeredSurface | None = None

        self._last_render_bucket = -1
        self._last_render_static_key: tuple[str, str, str] | None = None
        self._last_pill_pos: tuple[int, int] | None = None

        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    # -------------
    # Configuration
    # -------------
    def _min_hold_ms(self) -> int:
        try:
            return int(os.environ.get("MCP_OVERLAY_MIN_HOLD_MS", "450"))
        except Exception:
            return 450

    def _fade_ms(self) -> int:
        try:
            return int(os.environ.get("MCP_OVERLAY_FADE_MS", "260"))
        except Exception:
            return 260

    # -----------
    # Public API
    # -----------
    def show(self, x, y, text=""):
        self.queue.put(("show", (x, y, text)))

    def update_label(self, text):
        self.queue.put(("update_label", text))

    def status(self, text, color="yellow"):
        self.queue.put(("status", (text, color)))

    def hide(self):
        self.queue.put(("hide", None))

    def move(self, x, y):
        with self._cursor_lock:
            self._pending_cursor = (_clamp_int(x), _clamp_int(y))

    def stop(self):
        self.queue.put(("stop", None))

    # -----------------
    # Fonts / rendering
    # -----------------
    def _load_fonts(self):
        font_dir = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
        action_size = 14 * self._ss
        think_size = 10 * self._ss

        def try_font(paths, size):
            for p in paths:
                if os.path.exists(p):
                    try:
                        return ImageFont.truetype(p, size)
                    except Exception:
                        continue
            return None

        self._font_action = try_font(
            [
                os.path.join(font_dir, "segoeuiv.ttf"),  # Segoe UI Variable
                os.path.join(font_dir, "segoeui.ttf"),
            ],
            action_size,
        )
        self._font_thinking = try_font([os.path.join(font_dir, "segoeui.ttf")], think_size)

        if self._font_action is None:
            self._font_action = ImageFont.load_default()
        if self._font_thinking is None:
            self._font_thinking = ImageFont.load_default()

    def _status_color_rgb(self):
        c = (self._requested_status_color or "").lower()
        return {
            "yellow": (255, 230, 150),
            "orange": (255, 200, 150),
            "green": (170, 255, 200),
            "cyan": (170, 235, 255),
            "red": (255, 170, 170),
        }.get(c, (255, 230, 150))

    def _text_bbox(self, font, text: str):
        try:
            box = font.getbbox(text)
            return max(0, box[2] - box[0]), max(0, box[3] - box[1])
        except Exception:
            return font.getsize(text)

    def _line_height(self, font, sample_text: str) -> int:
        """
        Return a stable line height for the given font.
        PIL bbox heights can be 0 for some fallback fonts; getmetrics() is more reliable.
        """
        try:
            ascent, descent = font.getmetrics()
            h = int(ascent) + int(descent)
        except Exception:
            h = int(self._text_bbox(font, sample_text or "Ag")[1])
        return max(1, h+2)

    def _truncate_to_width(self, text: str, font, max_w: int) -> str:
        t = (text or "").strip()
        if not t:
            return ""
        w, _ = self._text_bbox(font, t)
        if w <= max_w:
            return t

        ell = "..."
        lo, hi = 0, len(t)
        best = ell
        while lo <= hi:
            mid = (lo + hi) // 2
            cand = t[:mid].rstrip() + ell
            cw, _ = self._text_bbox(font, cand)
            if cw <= max_w:
                best = cand
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    def _render_ring_rgba(self) -> Image.Image:
        ss = self._ss
        size = self._ring_size * ss
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        pad = 6 * ss
        d.ellipse(
            (pad - ss, pad - ss, size - pad + ss, size - pad + ss),
            outline=(217, 242, 255, 110),
            width=max(1, 1 * ss),
        )
        d.ellipse(
            (pad, pad, size - pad, size - pad),
            outline=(143, 211, 255, 170),
            width=max(1, 2 * ss),
        )
        return img.resize((self._ring_size, self._ring_size), Image.Resampling.LANCZOS)

    # def _render_pill_rgba(self, action: str, thinking: str, t_now: float) -> Image.Image:
    #     ss = self._ss
    #     pad_x = 14 * ss
    #     pad_y = 10 * ss
    #     gap_y = 6 * ss
    #     radius = 14 * ss
    #     max_w = 360 * ss

    #     action = (action or "").strip()
    #     thinking = (thinking or "").strip()

    #     # Fade-in + subtle slide on change.
    #     fade_ms = max(1, self._fade_ms())
    #     fade_t = min(1.0, max(0.0, (t_now - self._fade_started_at) / (fade_ms / 1000.0)))
    #     fade_e = 1.0 - (1.0 - fade_t) ** 3  # easeOutCubic
    #     slide_y = int(round((1.0 - fade_e) * 4 * ss))
    #     alpha_mul = fade_e

    #     # Pulse while thinking/waiting/scanning: flicker-ish fade in/out.
    #     think_alpha_mul = 1.0
    #     if self._pulse_enabled:
    #         phase = (t_now * 1.2) % 1.0
    #         s = 0.5 - 0.5 * math.cos(phase * 2.0 * math.pi)
    #         think_alpha_mul = 0.35 + 0.65 * (s**0.65)

    #     status_rgb = self._status_color_rgb()
    #     action_rgb = (245, 245, 245)
    #     thinking_rgb = status_rgb

    #     usable_w = max(1, max_w - 2 * pad_x)
    #     action = self._truncate_to_width(action, self._font_action, usable_w)
    #     thinking = self._truncate_to_width(thinking, self._font_thinking, usable_w)

    #     aw, ah_bbox = self._text_bbox(self._font_action, action or " ")
    #     ah = max(int(ah_bbox), self._line_height(self._font_action, action or "Ag"))
    #     tw, th = (0, 0)
    #     if thinking:
    #         tw, th_bbox = self._text_bbox(self._font_thinking, thinking)
    #         th = max(int(th_bbox), self._line_height(self._font_thinking, thinking or "Ag"))

    #     pill_w = min(max_w, max(aw, tw) + 2 * pad_x)
    #     pill_h = (th + gap_y + ah + 2 * pad_y) if thinking else (ah + 2 * pad_y)

    #     # Shadow and background.
    #     margin = 10 * ss
    #     win_w = int(pill_w + 2 * margin)
    #     win_h = int(pill_h + 2 * margin)
    #     base = Image.new("RGBA", (win_w, win_h), (0, 0, 0, 0))

    #     shadow = Image.new("RGBA", (win_w, win_h), (0, 0, 0, 0))
    #     sd = ImageDraw.Draw(shadow)
    #     sd.rounded_rectangle(
    #         (margin, margin + 1 * ss, margin + pill_w, margin + pill_h + 1 * ss),
    #         radius=radius,
    #         fill=(0, 0, 0, int(round(120 * alpha_mul))),
    #     )
    #     shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(1, 3 * ss)))
    #     base.alpha_composite(shadow)

    #     d = ImageDraw.Draw(base)
        
    #     # Pill Background with subtle vertical gradient
    #     pill_mask = Image.new("L", (win_w, win_h), 0)
    #     md = ImageDraw.Draw(pill_mask)
    #     md.rounded_rectangle(
    #         (margin, margin, margin + pill_w, margin + pill_h),
    #         radius=radius,
    #         fill=255,
    #     )
        
    #     gradient = Image.new("RGBA", (win_w, win_h), (0, 0, 0, 0))
    #     gd = ImageDraw.Draw(gradient)
    #     for y in range(int(margin), int(margin + pill_h)):
    #         # Subtle gradient from darker to slightly lighter
    #         rel_y = (y - margin) / pill_h
    #         # Blend from (16, 16, 16) to (32, 32, 32)
    #         color_v = int(16 + 16 * rel_y)
    #         gd.line((margin, y, margin + pill_w, y), fill=(color_v, color_v, color_v, int(round(230 * alpha_mul))))
            
    #     base.paste(gradient, (0, 0), pill_mask)

    #     # Center text horizontally inside the pill (requested).
    #     text_block_w = max(aw, tw)
    #     tx = margin + max(0, (pill_w - text_block_w) // 2)
    #     if thinking:
    #         ty_think = margin + pad_y + slide_y
    #         ty_action = ty_think + th + gap_y
    #         d.text(
    #             (tx, ty_think),
    #             thinking,
    #             font=self._font_thinking,
    #             fill=(*thinking_rgb, int(round(255 * alpha_mul * think_alpha_mul))),
    #         )
    #     else:
    #         ty_action = margin + (pill_h - ah) // 2 + slide_y

    #     d.text(
    #         (tx, ty_action),
    #         action,
    #         font=self._font_action,
    #         fill=(*action_rgb, int(round(255 * alpha_mul))),
    #     )

    #     out_w = max(1, win_w // ss)
    #     out_h = max(1, win_h // ss)
    #     if ss != 1:
    #         base = base.resize((out_w, out_h), Image.Resampling.LANCZOS)
    #     return base

    def _render_pill_rgba(self, action: str, thinking: str, t_now: float) -> Image.Image:
        ss = self._ss
        pad_x = 14 * ss
        pad_y = 10 * ss
        gap_y = 6 * ss
        radius = 14 * ss
        max_w = 360 * ss

        action = (action or "").strip()
        thinking = (thinking or "").strip()

        # Fade-in + subtle slide on change.
        fade_ms = max(1, self._fade_ms())
        fade_t = min(1.0, max(0.0, (t_now - self._fade_started_at) / (fade_ms / 1000.0)))
        fade_e = 1.0 - (1.0 - fade_t) ** 3  # easeOutCubic
        slide_y = int(round((1.0 - fade_e) * 4 * ss))
        alpha_mul = fade_e

        # Pulse while thinking/waiting/scanning: flicker-ish fade in/out.
        think_alpha_mul = 1.0
        if self._pulse_enabled:
            phase = (t_now * 1.2) % 1.0
            s = 0.5 - 0.5 * math.cos(phase * 2.0 * math.pi)
            think_alpha_mul = 0.35 + 0.65 * (s**0.65)

        status_rgb = self._status_color_rgb()
        
        if thinking:
            # If both are present, color the 'Thinking...' and keep action text white
            action_rgb = (245, 245, 245)
            thinking_rgb = status_rgb
        else:
            # If it's a standalone status prompt from server.py, apply the custom color to it!
            action_rgb = status_rgb
            thinking_rgb = status_rgb

        usable_w = max(1, max_w - 2 * pad_x)
        
        # USE THE SAME FONT FOR BOTH
        font_to_use = self._font_action
        
        action = self._truncate_to_width(action, font_to_use, usable_w)
        thinking = self._truncate_to_width(thinking, font_to_use, usable_w)

        aw, ah_bbox = self._text_bbox(font_to_use, action or " ")
        ah = max(int(ah_bbox), self._line_height(font_to_use, action or "Ag"))
        tw, th = (0, 0)
        if thinking:
            tw, th_bbox = self._text_bbox(font_to_use, thinking)
            th = max(int(th_bbox), self._line_height(font_to_use, thinking or "Ag"))

        pill_w = min(max_w, max(aw, tw) + 2 * pad_x)
        
        # Calculate height correctly to keep things perfectly centered
        if thinking and action:
            pill_h = th + gap_y + ah + 2 * pad_y
        elif thinking and not action:
            pill_h = th + 2 * pad_y
        elif action and not thinking:
            pill_h = ah + 2 * pad_y
        else:
            pill_h = 2 * pad_y

        # Shadow and background.
        margin = 10 * ss
        win_w = int(pill_w + 2 * margin)
        win_h = int(pill_h + 2 * margin)
        base = Image.new("RGBA", (win_w, win_h), (0, 0, 0, 0))

        shadow = Image.new("RGBA", (win_w, win_h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle(
            (margin, margin + 1 * ss, margin + pill_w, margin + pill_h + 1 * ss),
            radius=radius,
            fill=(0, 0, 0, int(round(120 * alpha_mul))),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(1, 3 * ss)))
        base.alpha_composite(shadow)

        d = ImageDraw.Draw(base)
        
        # Pill Background with subtle vertical gradient
        pill_mask = Image.new("L", (win_w, win_h), 0)
        md = ImageDraw.Draw(pill_mask)
        md.rounded_rectangle(
            (margin, margin, margin + pill_w, margin + pill_h),
            radius=radius,
            fill=255,
        )
        
        gradient = Image.new("RGBA", (win_w, win_h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(gradient)
        for y in range(int(margin), int(margin + pill_h)):
            rel_y = (y - margin) / pill_h
            color_v = int(16 + 16 * rel_y)
            gd.line((margin, y, margin + pill_w, y), fill=(color_v, color_v, color_v, int(round(230 * alpha_mul))))
            
        base.paste(gradient, (0, 0), pill_mask)

        # Draw Text Centered
        tx_think = margin + max(0, (pill_w - tw) // 2)
        tx_action = margin + max(0, (pill_w - aw) // 2)

        if thinking and action:
            ty_think = margin + pad_y + slide_y
            ty_action = ty_think + th + gap_y
            d.text((tx_think, ty_think), thinking, font=font_to_use, fill=(*thinking_rgb, int(round(255 * alpha_mul * think_alpha_mul))))
            d.text((tx_action, ty_action), action, font=font_to_use, fill=(*action_rgb, int(round(255 * alpha_mul))))
        elif thinking and not action:
            ty_think = margin + (pill_h - th) // 2 + slide_y
            d.text((tx_think, ty_think), thinking, font=font_to_use, fill=(*thinking_rgb, int(round(255 * alpha_mul * think_alpha_mul))))
        elif action and not thinking:
            ty_action = margin + (pill_h - ah) // 2 + slide_y
            d.text((tx_action, ty_action), action, font=font_to_use, fill=(*action_rgb, int(round(255 * alpha_mul))))

        out_w = max(1, win_w // ss)
        out_h = max(1, win_h // ss)
        if ss != 1:
            base = base.resize((out_w, out_h), Image.Resampling.LANCZOS)
        return base

    # ----------------------------
    # Win32: layered window plumbing
    # ----------------------------
    def _register_window_class(self):
        wc = win32gui.WNDCLASS()
        wc.style = 0
        wc.hInstance = win32gui.GetModuleHandle(None)
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        wc.hbrBackground = 0
        wc.lpszClassName = "ComputerUseOverlayLayered"

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == win32con.WM_DESTROY:
                try:
                    win32gui.PostQuitMessage(0)
                except Exception:
                    pass
                return 0
            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        wc.lpfnWndProc = wndproc
        try:
            win32gui.RegisterClass(wc)
        except Exception:
            # Already registered in this process.
            pass

    def _create_layered_window(self, title: str, w: int, h: int) -> int:
        ex_style = (
            win32con.WS_EX_LAYERED
            | win32con.WS_EX_TOPMOST
            | win32con.WS_EX_TOOLWINDOW
            | win32con.WS_EX_TRANSPARENT
            | 0x08000000  # WS_EX_NOACTIVATE
        )
        style = win32con.WS_POPUP
        hwnd = win32gui.CreateWindowEx(
            ex_style,
            "ComputerUseOverlayLayered",
            title,
            style,
            -2000,
            -2000,
            max(1, int(w)),
            max(1, int(h)),
            0,
            0,
            win32gui.GetModuleHandle(None),
            None,
        )
        win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
        return hwnd

    def _set_window_pos_noactivate(self, hwnd: int, x: int, y: int, w: int | None = None, h: int | None = None):
        flags = win32con.SWP_NOACTIVATE | win32con.SWP_NOSENDCHANGING
        if w is None or h is None:
            flags |= win32con.SWP_NOSIZE
            w = 0
            h = 0
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, int(x), int(y), int(w), int(h), flags)

    def _ensure_surface(self, hwnd: int, desired_w: int, desired_h: int, existing: _LayeredSurface | None) -> _LayeredSurface:
        desired_w = max(1, int(desired_w))
        desired_h = max(1, int(desired_h))
        if existing is not None and existing.w == desired_w and existing.h == desired_h:
            return existing

        # Destroy existing surface.
        if existing is not None:
            try:
                _GDI32.SelectObject(existing.hdc_mem, existing.hbmp_old)
            except Exception:
                pass
            try:
                _GDI32.DeleteObject(existing.hbmp)
            except Exception:
                pass
            try:
                _GDI32.DeleteDC(existing.hdc_mem)
            except Exception:
                pass

        assert self._hdc_screen is not None
        hdc_mem = _GDI32.CreateCompatibleDC(self._hdc_screen)

        BI_RGB = 0
        DIB_RGB_COLORS = 0

        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = desired_w
        bmi.bmiHeader.biHeight = -desired_h  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        bmi.bmiHeader.biSizeImage = desired_w * desired_h * 4

        bits_ptr = ctypes.c_void_p()
        hbmp = _GDI32.CreateDIBSection(
            self._hdc_screen, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits_ptr), None, 0
        )
        hbmp_old = _GDI32.SelectObject(hdc_mem, hbmp)

        return _LayeredSurface(
            hwnd=hwnd,
            hdc_mem=hdc_mem,
            hbmp=hbmp,
            hbmp_old=hbmp_old,
            bits_ptr=bits_ptr,
            w=desired_w,
            h=desired_h,
        )

    def _blit(self, surf: _LayeredSurface, x: int, y: int, img_rgba: Image.Image):
        # UpdateLayeredWindow works best with BGRA premultiplied alpha.
        img = img_rgba.convert("RGBA")
        r, g, b, a = img.split()
        r = ImageChops.multiply(r, a)
        g = ImageChops.multiply(g, a)
        b = ImageChops.multiply(b, a)
        premul = Image.merge("RGBA", (r, g, b, a))
        bgra = premul.tobytes("raw", "BGRA")

        # Copy bytes into the DIB section and update.
        ctypes.memmove(surf.bits_ptr, bgra, min(len(bgra), surf.w * surf.h * 4))

        assert self._hdc_screen is not None
        win32gui.UpdateLayeredWindow(
            surf.hwnd,
            self._hdc_screen,
            (int(x), int(y)),
            (int(surf.w), int(surf.h)),
            surf.hdc_mem,
            (0, 0),
            0,
            (0, 0, 255, 1),  # (BlendOp, BlendFlags, SourceConstantAlpha, AlphaFormat)
            win32con.ULW_ALPHA,
        )

    # ------------------------
    # Queue / state transitions
    # ------------------------
    def _set_pulse_enabled(self, enabled: bool):
        self._pulse_enabled = bool(enabled)

    def _apply_pending_cursor(self):
        with self._cursor_lock:
            pending = self._pending_cursor
            self._pending_cursor = None
        if pending is not None:
            self._last_cursor = pending

    def _maybe_apply_pending_text(self, now: float):
        if not self._pending_text:
            return
        min_hold_s = max(0, self._min_hold_ms()) / 1000.0
        if (now - self._last_text_set_at) < min_hold_s:
            return
        a, t = self._pending_text
        self._pending_text = None
        self._apply_text(a, t, now, force=True)

    def _apply_text(self, action: str, thinking: str, now: float, force: bool = False):
        min_hold_s = max(0, self._min_hold_ms()) / 1000.0
        if not force and self._visible and (now - self._last_text_set_at) < min_hold_s:
            self._pending_text = (action, thinking)
            return

        self._current_action = (action or "").strip()
        self._current_thinking = (thinking or "").strip()
        self._last_text_set_at = now
        self._fade_started_at = now

        a = self._current_action.lower()
        # Pulse/flicker while the agent is waiting, scanning, or capturing.
        should_pulse = (
            bool(self._current_thinking)
            or ("processing" in a)
            or ("waiting" in a)
            or ("scanning" in a)
            or ("capturing" in a)
            or ("screenshot" in a)
        )
        self._set_pulse_enabled(should_pulse)

        # Force rerender.
        self._last_render_bucket = -1
        self._last_render_static_key = None

    def _process_queue(self, now: float):
        last_label = None
        last_status = None
        do_hide = False
        do_stop = False
        do_show = None

        while not self.queue.empty():
            cmd, args = self.queue.get()
            if cmd == "show":
                do_show = args
            elif cmd == "update_label":
                last_label = args
            elif cmd == "status":
                last_status = args
            elif cmd == "hide":
                do_hide = True
            elif cmd == "stop":
                do_stop = True

        if do_stop:
            self.running = False
            return

        if do_hide:
            self._visible = False
            if self._hwnd_pill:
                try:
                    win32gui.ShowWindow(self._hwnd_pill, win32con.SW_HIDE)
                except Exception:
                    pass
            if self._hwnd_ring:
                try:
                    win32gui.ShowWindow(self._hwnd_ring, win32con.SW_HIDE)
                except Exception:
                    pass

        if do_show is not None:
            x, y, text = do_show
            thinking = ""
            if "|" in text:
                thinking, text = text.split("|", 1)
            self._last_cursor = (_clamp_int(x), _clamp_int(y))
            self._visible = True
            self._apply_text(text, thinking, now, force=True)

        if last_status is not None:
            text, color = last_status
            self._requested_status_color = color
            thinking = ""
            if "|" in text:
                thinking, text = text.split("|", 1)
            self._visible = True
            self._apply_text(text, thinking, now, force=False)

        if last_label is not None:
            text = last_label
            thinking = ""
            if "|" in text:
                thinking, text = text.split("|", 1)
            self._visible = True
            self._apply_text(text, thinking, now, force=False)

    # -------------
    # Thread main
    # -------------
    def _run(self):
        if sys.platform != "win32":
            return
        try:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                pass

            self._load_fonts()
            self._register_window_class()

            self._hdc_screen = win32gui.GetDC(0)
            self._hwnd_pill = self._create_layered_window("ComputerUseOverlay", 420, 90)
            self._hwnd_ring = self._create_layered_window("ComputerUseCursorRing", self._ring_size, self._ring_size)

            # Init ring once.
            ring_img = self._render_ring_rgba()
            self._surf_ring = self._ensure_surface(self._hwnd_ring, ring_img.size[0], ring_img.size[1], None)
            self._blit(self._surf_ring, -2000, -2000, ring_img)

            while self.running:
                now = time.perf_counter()

                self._process_queue(now)
                self._maybe_apply_pending_text(now)

                # Always follow the *real* cursor for perfect sync (even on manual movement).
                pos = _get_cursor_pos()
                if pos is not None:
                    with self._cursor_lock:
                        if self._pending_cursor is None:
                            self._last_cursor = pos
                self._apply_pending_cursor()

                if self._visible and self._last_cursor is not None:
                    cx, cy = self._last_cursor

                    # Ring centered on cursor.
                    rx = int(cx - self._ring_size // 2)
                    ry = int(cy - self._ring_size // 2)
                    try:
                        win32gui.ShowWindow(self._hwnd_ring, win32con.SW_SHOWNOACTIVATE)
                        self._set_window_pos_noactivate(self._hwnd_ring, rx, ry)
                    except Exception:
                        pass

                    # Pill near cursor.
                    px = int(cx + self._offset_x)
                    py = int(cy + self._offset_y)

                    fade_active = (now - self._fade_started_at) < (self._fade_ms() / 1000.0)
                    pulse_active = self._pulse_enabled
                    bucket = int(now * 24) if (fade_active or pulse_active) else 0  # animation timestep
                    static_key = (self._current_action, self._current_thinking, self._requested_status_color)
                    needs_render = (bucket != self._last_render_bucket) or (static_key != self._last_render_static_key)

                    if needs_render:
                        pill_img = self._render_pill_rgba(self._current_action, self._current_thinking, now)
                        self._surf_pill = self._ensure_surface(self._hwnd_pill, pill_img.size[0], pill_img.size[1], self._surf_pill)
                        self._blit(self._surf_pill, px, py, pill_img)
                        self._last_render_bucket = bucket
                        self._last_render_static_key = static_key
                        self._last_pill_pos = (px, py)
                        try:
                            win32gui.ShowWindow(self._hwnd_pill, win32con.SW_SHOWNOACTIVATE)
                        except Exception:
                            pass
                    else:
                        # Just move without re-blitting.
                        if self._last_pill_pos != (px, py):
                            self._set_window_pos_noactivate(self._hwnd_pill, px, py)
                            self._last_pill_pos = (px, py)
                else:
                    try:
                        if self._hwnd_pill:
                            win32gui.ShowWindow(self._hwnd_pill, win32con.SW_HIDE)
                    except Exception:
                        pass
                    try:
                        if self._hwnd_ring:
                            win32gui.ShowWindow(self._hwnd_ring, win32con.SW_HIDE)
                    except Exception:
                        pass

                # Keep message queue flowing.
                try:
                    win32gui.PumpWaitingMessages()
                except Exception:
                    pass

                # Sleep: smooth while animating, cheaper when idle/hidden.
                if self._visible and (pulse_active or fade_active):
                    time.sleep(0.016)
                elif self._visible:
                    time.sleep(0.02)
                else:
                    time.sleep(0.06)

            # Cleanup surfaces/windows.
            for surf in (self._surf_pill, self._surf_ring):
                if surf is None:
                    continue
                try:
                    _GDI32.SelectObject(surf.hdc_mem, surf.hbmp_old)
                except Exception:
                    pass
                try:
                    _GDI32.DeleteObject(surf.hbmp)
                except Exception:
                    pass
                try:
                    _GDI32.DeleteDC(surf.hdc_mem)
                except Exception:
                    pass

            try:
                if self._hwnd_pill:
                    win32gui.DestroyWindow(self._hwnd_pill)
            except Exception:
                pass
            try:
                if self._hwnd_ring:
                    win32gui.DestroyWindow(self._hwnd_ring)
            except Exception:
                pass
            try:
                if self._hdc_screen:
                    win32gui.ReleaseDC(0, self._hdc_screen)
            except Exception:
                pass
        except Exception:
            print("[OVERLAY]: Fatal error:\n" + traceback.format_exc(), file=sys.stderr)
            self.running = False
