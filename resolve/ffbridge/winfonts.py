"""Windows font enumeration via GDI; no font files are redistributed."""
import ctypes
from ctypes import wintypes


def enumerate_fonts(use_cache=True):
    if not hasattr(ctypes, "WinDLL"):
        return {}

    class LOGFONTW(ctypes.Structure):
        _fields_ = [(n, wintypes.LONG) for n in ("height", "width", "escapement", "orientation", "weight")] + [
            (n, ctypes.c_ubyte) for n in ("italic", "underline", "strikeout", "charset", "outprecision", "clipprecision", "quality", "pitch")
        ] + [("face", ctypes.c_wchar * 32)]

    class ENUMLOGFONTEXW(ctypes.Structure):
        _fields_ = [("font", LOGFONTW), ("fullname", ctypes.c_wchar * 64),
                    ("style", ctypes.c_wchar * 32), ("script", ctypes.c_wchar * 32)]

    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.POINTER(ENUMLOGFONTEXW),
                                      ctypes.c_void_p, wintypes.DWORD, ctypes.c_ssize_t)
    gdi.EnumFontFamiliesExW.argtypes = [wintypes.HDC, ctypes.POINTER(LOGFONTW), callback_type, ctypes.c_ssize_t, wintypes.DWORD]
    gdi.EnumFontFamiliesExW.restype = ctypes.c_int
    fonts = {}

    @callback_type
    def collect(record, metric, kind, parameter):
        family = record.contents.font.face
        if family and not family.startswith("@"):
            styles = fonts.setdefault(family.lower(), [])
            style = record.contents.style or "Regular"
            if style not in styles:
                styles.append(style)
        return 1

    dc = gdi.CreateCompatibleDC(None)
    if not dc:
        return {}
    try:
        query = LOGFONTW()
        query.charset = 1  # DEFAULT_CHARSET
        gdi.EnumFontFamiliesExW(dc, ctypes.byref(query), collect, 0, 0)
    finally:
        gdi.DeleteDC(dc)
    return fonts
