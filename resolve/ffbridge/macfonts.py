"""Enumerating installed fonts on macOS.

Three approaches were tried. ``system_profiler -json SPFontsDataType`` returns
an empty document on macOS 27, and shelling out cost nine seconds even when it
worked, so it is not used. PyObjC would be ideal but is not guaranteed to exist
inside DaVinci Resolve's embedded Python.

What is left is CoreText through ``ctypes``, which is present on every Mac,
needs no third-party package, and answers in well under a second. The result is
cached on disk because a font list changes rarely and an import should not pay
for it twice.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import os
import time
from typing import Dict, List, Optional

from .paths import support_dir

_CACHE_NAME = "fonts.cache.json"
#: Fonts are installed rarely; a day is long enough to make repeat imports
#: instant and short enough that a newly installed font shows up the same day.
_CACHE_TTL_SECONDS = 86400.0

_kCFStringEncodingUTF8 = 0x08000100


class _CoreText:
    """Thin ctypes binding to the few CoreText calls needed here."""

    def __init__(self) -> None:
        cf_path = ctypes.util.find_library("CoreFoundation")
        ct_path = ctypes.util.find_library("CoreText")
        if not cf_path or not ct_path:
            raise OSError("CoreFoundation or CoreText not found")

        self.cf = ctypes.cdll.LoadLibrary(cf_path)
        self.ct = ctypes.cdll.LoadLibrary(ct_path)

        self.cf.CFArrayGetCount.restype = ctypes.c_long
        self.cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
        self.cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
        self.cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
        self.cf.CFStringGetCString.restype = ctypes.c_bool
        self.cf.CFStringGetCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32
        ]
        self.cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        self.cf.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32
        ]
        self.cf.CFDictionaryCreate.restype = ctypes.c_void_p
        self.cf.CFDictionaryCreate.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p,
        ]
        self.cf.CFRelease.argtypes = [ctypes.c_void_p]

        self.ct.CTFontManagerCopyAvailableFontFamilyNames.restype = ctypes.c_void_p
        self.ct.CTFontDescriptorCreateWithAttributes.restype = ctypes.c_void_p
        self.ct.CTFontDescriptorCreateWithAttributes.argtypes = [ctypes.c_void_p]
        self.ct.CTFontDescriptorCreateMatchingFontDescriptors.restype = ctypes.c_void_p
        self.ct.CTFontDescriptorCreateMatchingFontDescriptors.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p
        ]
        self.ct.CTFontDescriptorCopyAttribute.restype = ctypes.c_void_p
        self.ct.CTFontDescriptorCopyAttribute.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        self._family_attr = self._global("kCTFontFamilyNameAttribute")
        self._style_attr = self._global("kCTFontStyleNameAttribute")

    def _global(self, name: str) -> ctypes.c_void_p:
        return ctypes.c_void_p.in_dll(self.ct, name)

    def _to_str(self, cfstr: Optional[int]) -> str:
        if not cfstr:
            return ""
        buf = ctypes.create_string_buffer(512)
        if self.cf.CFStringGetCString(cfstr, buf, 512, _kCFStringEncodingUTF8):
            return buf.value.decode("utf-8", "replace")
        return ""

    def _from_str(self, text: str) -> ctypes.c_void_p:
        return ctypes.c_void_p(
            self.cf.CFStringCreateWithCString(None, text.encode("utf-8"), _kCFStringEncodingUTF8)
        )

    def families(self) -> List[str]:
        arr = self.ct.CTFontManagerCopyAvailableFontFamilyNames()
        if not arr:
            return []
        try:
            count = self.cf.CFArrayGetCount(arr)
            return [
                name
                for i in range(count)
                if (name := self._to_str(self.cf.CFArrayGetValueAtIndex(arr, i)))
            ]
        finally:
            self.cf.CFRelease(arr)

    def styles_for(self, family: str) -> List[str]:
        key = self._from_str(family)
        if not key.value:
            return []
        keys = (ctypes.c_void_p * 1)(self._family_attr)
        values = (ctypes.c_void_p * 1)(key)
        attrs = self.cf.CFDictionaryCreate(None, keys, values, 1, None, None)
        if not attrs:
            self.cf.CFRelease(key)
            return []

        descriptor = self.ct.CTFontDescriptorCreateWithAttributes(attrs)
        matches = (
            self.ct.CTFontDescriptorCreateMatchingFontDescriptors(descriptor, None)
            if descriptor
            else None
        )

        out: List[str] = []
        if matches:
            for i in range(self.cf.CFArrayGetCount(matches)):
                desc = self.cf.CFArrayGetValueAtIndex(matches, i)
                style_ref = self.ct.CTFontDescriptorCopyAttribute(desc, self._style_attr)
                style = self._to_str(style_ref)
                if style_ref:
                    self.cf.CFRelease(style_ref)
                if style and style not in out:
                    out.append(style)
            self.cf.CFRelease(matches)
        if descriptor:
            self.cf.CFRelease(descriptor)
        self.cf.CFRelease(attrs)
        self.cf.CFRelease(key)
        return out


def _cache_path() -> str:
    return os.path.join(support_dir(), _CACHE_NAME)


def _read_cache() -> Optional[Dict[str, List[str]]]:
    path = _cache_path()
    try:
        if not os.path.exists(path):
            return None
        if time.time() - os.path.getmtime(path) > _CACHE_TTL_SECONDS:
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) and data else None
    except (OSError, ValueError):
        return None


def _write_cache(catalogue: Dict[str, List[str]]) -> None:
    try:
        os.makedirs(support_dir(), exist_ok=True)
        tmp = _cache_path() + ".part"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(catalogue, fh)
        os.replace(tmp, _cache_path())
    except OSError:
        pass


def enumerate_fonts(use_cache: bool = True) -> Dict[str, List[str]]:
    """Family (lowercased) -> available style names.

    An empty result means "could not enumerate", which the resolver treats as
    "report every font as missing". That is the honest failure: claiming a font
    resolved without checking would silently substitute a typeface.
    """
    if use_cache:
        cached = _read_cache()
        if cached is not None:
            return cached

    try:
        ct = _CoreText()
        catalogue: Dict[str, List[str]] = {}
        for family in ct.families():
            styles = ct.styles_for(family) or ["Regular"]
            catalogue[family.lower()] = styles
    except Exception:
        return {}

    if catalogue:
        _write_cache(catalogue)
    return catalogue
