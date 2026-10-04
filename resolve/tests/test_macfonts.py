"""CoreText font enumeration.

Marked as integration: it reads the fonts actually installed on the machine.
It is worth having because the two obvious alternatives both failed —
``system_profiler -json SPFontsDataType`` returns an empty document on
macOS 27, and PyObjC is not guaranteed inside Resolve's embedded Python.
"""

import sys
import time

import pytest

from ffbridge.macfonts import enumerate_fonts

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


def test_enumeration_finds_fonts():
    cat = enumerate_fonts(use_cache=False)
    assert len(cat) > 10, "no fonts found; CoreText binding is broken"


def test_families_are_lowercased_keys_with_style_lists():
    cat = enumerate_fonts(use_cache=False)
    key = next(iter(cat))
    assert key == key.lower()
    assert isinstance(cat[key], list) and cat[key]


def test_a_system_font_is_present_with_real_styles():
    cat = enumerate_fonts(use_cache=False)
    helvetica = cat.get("helvetica")
    assert helvetica, "Helvetica should exist on every Mac"
    assert "Regular" in helvetica and "Bold" in helvetica


def test_enumeration_is_fast_enough_to_run_during_an_import():
    """The previous implementation took nine seconds, which is a visible stall
    on every transfer."""
    start = time.time()
    enumerate_fonts(use_cache=False)
    assert time.time() - start < 2.0
