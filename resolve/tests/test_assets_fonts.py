"""Asset cache and font resolution."""

import os
import tempfile

import pytest

from ffbridge.assets import AssetCache, extension_for, sha256_bytes
from ffbridge.fonts import EXACT, MISSING, STYLE_APPROXIMATED, STYLE_FALLBACK, FontResolver, is_italic, weight_from_style


@pytest.fixture
def cache():
    return AssetCache(tempfile.mkdtemp())


def test_identical_images_are_stored_once(cache):
    """A logo used twenty times must be one file, not twenty."""
    a = cache.store(b"same-bytes", "image/png", "logo.png")
    b = cache.store(b"same-bytes", "image/png", "logo-again.png")
    assert a.path == b.path
    assert os.path.getsize(a.path) == len(b"same-bytes")
    # One payload on disk, whatever the reference count.
    payloads = [
        f for _, _, files in os.walk(cache.root) for f in files if not f.endswith(".name")
    ]
    assert len(payloads) == 1


def test_total_size_reports_real_disk_use_including_sidecars(cache):
    """The number shown in Settings is disk usage, so it counts everything the
    cache actually wrote — not just the payloads."""
    cache.store(b"same-bytes", "image/png", "logo.png")
    assert cache.total_size() > len(b"same-bytes")


def test_different_images_get_different_paths(cache):
    a = cache.store(b"one", "image/png", "a.png")
    b = cache.store(b"two", "image/png", "b.png")
    assert a.path != b.path


def test_a_corrupted_upload_is_rejected_not_cached(cache):
    """Otherwise truncated bytes get cached under a hash they do not have and
    are served to every future transfer."""
    with pytest.raises(ValueError):
        cache.store(b"actual", "image/png", "x.png", expected_digest="0" * 64)


def test_matching_checksum_is_accepted(cache):
    data = b"verified"
    stored = cache.store(data, "image/png", "x.png", expected_digest=sha256_bytes(data))
    assert os.path.exists(stored.path)


def test_paths_are_sharded_to_keep_directories_small(cache):
    stored = cache.store(b"x", "image/png", "x.png")
    rel = os.path.relpath(stored.path, cache.root)
    assert len(rel.split(os.sep)) == 3


def test_missing_reports_only_uncached_assets(cache):
    data = b"present"
    cache.store(data, "image/png", "p.png")
    assets = [
        {"id": "a", "sha256": sha256_bytes(data), "mimeType": "image/png", "suggestedName": "p.png"},
        {"id": "b", "sha256": "f" * 64, "mimeType": "image/png", "suggestedName": "q.png"},
    ]
    assert cache.missing(assets) == ["b"]
    assert set(cache.resolve_paths(assets)) == {"a"}


def test_recent_files_are_not_pruned_even_when_unreferenced(cache):
    """An asset unreferenced right now may be referenced again the moment the
    user reopens a project."""
    cache.store(b"keep", "image/png", "k.png")
    removed, _ = cache.prune_orphans(referenced=[], older_than_days=30)
    assert removed == 0


def test_old_unreferenced_files_are_pruned(cache):
    stored = cache.store(b"old", "image/png", "o.png")
    os.utime(stored.path, (0, 0))
    removed, freed = cache.prune_orphans(referenced=[], older_than_days=1)
    assert removed == 1 and freed > 0


def test_referenced_files_survive_pruning(cache):
    stored = cache.store(b"live", "image/png", "l.png")
    os.utime(stored.path, (0, 0))
    removed, _ = cache.prune_orphans(referenced=[stored.asset_id], older_than_days=1)
    assert removed == 0


@pytest.mark.parametrize("mime,expected", [
    ("image/png", ".png"), ("image/jpeg", ".jpg"),
    ("image/svg+xml", ".svg"), ("image/webp", ".webp"),
])
def test_extensions_follow_the_mime_type(mime, expected):
    assert extension_for(mime) == expected


def test_unknown_mime_falls_back_to_the_supplied_name():
    assert extension_for("application/octet-stream", "thing.tiff") == ".tiff"


# -- fonts -----------------------------------------------------------------

@pytest.mark.parametrize("style,weight", [
    ("Thin", 100), ("Light", 300), ("Regular", 400), ("Medium", 500),
    ("SemiBold", 600), ("Bold", 700), ("ExtraBold", 800), ("Black", 900),
])
def test_weight_words_map_to_numbers(style, weight):
    assert weight_from_style(style) == weight


def test_longer_weight_words_win_over_substrings():
    """"extrabold" must not be read as "bold", and "semibold" must not either —
    a 600 silently becoming a 700 is easy to miss visually."""
    assert weight_from_style("ExtraBold") == 800
    assert weight_from_style("Semi Bold") == 600
    assert weight_from_style("UltraLight") == 200


@pytest.mark.parametrize("style", ["Italic", "Bold Italic", "Oblique"])
def test_slant_is_detected(style):
    assert is_italic(style)


def test_exact_match_is_reported_as_exact():
    r = FontResolver({"inter": ["Regular", "Bold"]})
    assert r.resolve("Inter", "Bold").confidence == EXACT


def test_same_weight_different_spelling_is_approximated_not_exact():
    r = FontResolver({"inter": ["Semi Bold"]})
    m = r.resolve("Inter", "SemiBold")
    assert m.confidence == STYLE_APPROXIMATED and m.style == "Semi Bold"


def test_absent_weight_falls_back_to_the_nearest_and_says_so():
    r = FontResolver({"inter": ["Regular", "Bold"]})
    m = r.resolve("Inter", "Black")
    assert m.confidence == STYLE_FALLBACK and m.note


def test_slant_is_preferred_over_weight_when_choosing_a_fallback():
    r = FontResolver({"inter": ["Bold", "Light Italic"]})
    m = r.resolve("Inter", "Black Italic")
    assert m.style == "Light Italic"


def test_absent_family_is_missing_and_never_silently_substituted():
    r = FontResolver({"inter": ["Regular"]})
    m = r.resolve("Neue Haas Grotesk Display Pro", "Medium")
    assert m.confidence == MISSING
    assert m.family == "Neue Haas Grotesk Display Pro"  # original name kept
    assert "not installed" in m.note


def test_an_empty_catalogue_reports_missing_rather_than_claiming_success():
    m = FontResolver({}).resolve("Inter", "Regular")
    assert m.confidence == MISSING
