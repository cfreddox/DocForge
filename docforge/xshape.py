"""Optional X11 window shaping for a frameless, nonrectangular drop target.

Never required for conversion.  GNOME Wayland's compositor may choose not to
honor all XWayland shape or position requests; we fail gracefully.
"""
from __future__ import annotations

import ctypes
import os
from functools import lru_cache
from PIL import Image


@lru_cache(maxsize=1)
def _xlibs():
    if not os.environ.get("DISPLAY"):
        return None
    try:
        x11 = ctypes.CDLL("libX11.so.6")
        ext = ctypes.CDLL("libXext.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XCreateBitmapFromData.restype = ctypes.c_ulong
        x11.XCreateBitmapFromData.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                               ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
        x11.XFreePixmap.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x11.XFlush.argtypes = [ctypes.c_void_p]
        ext.XShapeCombineMask.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                                         ctypes.c_int, ctypes.c_int, ctypes.c_ulong, ctypes.c_int]
        return x11, ext
    except (OSError, AttributeError):
        return None


def set_window_shape(window, rgba: Image.Image, threshold: int = 10) -> bool:
    """Shape X11 window's visual and pointer hit regions according to rendered alpha."""
    libs = _xlibs()
    if not libs:
        return False
    x11, ext = libs
    try:
        # Tk's wm frame is the outermost native XID, rather than a Canvas child.
        native = window.tk.call("wm", "frame", window._w)
        xid = int(native, 0) if isinstance(native, str) else int(native)
        mono = rgba.getchannel("A").point(lambda a: 255 if a >= threshold else 0).convert("1")
        data = mono.tobytes()
        # PIL encodes mode-1 pixels MSB first; X11 XBM bitmaps use LSB first.
        reverse = bytes(int(f"{n:08b}"[::-1], 2) for n in range(256))
        bits = bytes(data).translate(reverse)
        buf = ctypes.create_string_buffer(bits)
        display = x11.XOpenDisplay(None)
        if not display:
            return False
        try:
            mask = x11.XCreateBitmapFromData(display, xid, buf, rgba.width, rgba.height)
            if not mask:
                return False
            try:
                ext.XShapeCombineMask(display, xid, 0, 0, 0, mask, 0)  # bounding
                ext.XShapeCombineMask(display, xid, 2, 0, 0, mask, 0)  # input
                x11.XFlush(display)
            finally:
                x11.XFreePixmap(display, mask)
        finally:
            x11.XCloseDisplay(display)
        return True
    except (ValueError, OSError, TypeError, Exception):
        return False


def request_borderless_managed_window(window) -> bool:
    """Ask X11 WM to omit decorations *without* overriding window management.

    This avoids the old always-on-top/Alt-Tab problems from overrideredirect.
    GNOME/Mutter normally honors _MOTIF_WM_HINTS; some compositors may not.
    """
    libs = _xlibs()
    if not libs:
        return False
    x11, _ = libs
    try:
        x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        x11.XInternAtom.restype = ctypes.c_ulong
        x11.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                       ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        display = x11.XOpenDisplay(None)
        if not display:
            return False
        try:
            xid = int(window.tk.call("wm", "frame", window._w), 0)
            if xid <= 0:
                return False
            atom = x11.XInternAtom(display, b"_MOTIF_WM_HINTS", 0)
            if not atom:
                return False
            # MWM_HINTS_DECORATIONS=2, decorations=0 (all window borders off).
            hints = (ctypes.c_ulong * 5)(2, 0, 0, 0, 0)
            x11.XChangeProperty(display, xid, atom, atom, 32, 0,
                                ctypes.cast(hints, ctypes.c_void_p), 5)
            x11.XFlush(display)
        finally:
            x11.XCloseDisplay(display)
        return True
    except (ValueError, OSError, TypeError):
        return False
