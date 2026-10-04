"""Content-addressed asset cache.

Images are stored under their own SHA-256, which gives deduplication for free:
a logo placed twenty times in a design is one file on disk and one transfer over
the wire, however many layers reference it. It also makes re-sync cheap — the
producer can ask "do you already have this hash?" before uploading anything.

The trade-off of content addressing is that filenames stop being readable, so
the original name is kept alongside as a sidecar. Fusion shows the file path in
the Loader, and ``a3f9…png`` in the Inspector is unhelpful when a designer is
trying to work out which image is which.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from .naming import sanitize
from .paths import assets_dir, ensure_dirs

_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "application/pdf": ".pdf",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extension_for(mime: str, suggested_name: str = "") -> str:
    ext = _EXTENSIONS.get((mime or "").lower())
    if ext:
        return ext
    _, dot_ext = os.path.splitext(suggested_name or "")
    return dot_ext.lower() if dot_ext else ".bin"


@dataclass
class CachedAsset:
    asset_id: str
    path: str
    byte_length: int
    mime_type: str
    original_name: str = ""


class AssetCache:
    """Stores transferred assets under ``~/Library/Application Support``."""

    def __init__(self, root: Optional[str] = None) -> None:
        self.root = root or assets_dir()
        os.makedirs(self.root, exist_ok=True)

    # -- paths -------------------------------------------------------------

    def _shard(self, digest: str) -> str:
        """Two-level fan-out.

        A flat directory with tens of thousands of files makes Finder and some
        filesystem operations crawl; two hex characters per level keeps any one
        directory small without making paths unwieldy.
        """
        return os.path.join(self.root, digest[:2], digest[2:4])

    def path_for(self, digest: str, mime: str = "", suggested_name: str = "") -> str:
        return os.path.join(self._shard(digest), digest + extension_for(mime, suggested_name))

    def has(self, digest: str, mime: str = "", suggested_name: str = "") -> bool:
        return os.path.exists(self.path_for(digest, mime, suggested_name))

    # -- writing -----------------------------------------------------------

    def store(
        self, data: bytes, mime: str = "", suggested_name: str = "", expected_digest: str = ""
    ) -> CachedAsset:
        """Store bytes, verifying the digest if one was supplied.

        Verification is not paranoia: a truncated upload would otherwise be
        cached under the *correct* hash of the *wrong* bytes and then served to
        every future transfer.
        """
        digest = sha256_bytes(data)
        if expected_digest and expected_digest != digest:
            raise ValueError(
                f"Asset content does not match its checksum "
                f"(expected {expected_digest[:12]}…, got {digest[:12]}…)"
            )

        path = self.path_for(digest, mime, suggested_name)
        os.makedirs(os.path.dirname(path), exist_ok=True)

        if not os.path.exists(path):
            # Write to a temporary name and rename, so a crash mid-write cannot
            # leave a half-file that later looks like a valid cache hit.
            tmp = path + ".part"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)

        if suggested_name:
            with open(path + ".name", "w", encoding="utf-8") as fh:
                fh.write(suggested_name)

        return CachedAsset(digest, path, len(data), mime, suggested_name)

    # -- reading -----------------------------------------------------------

    def resolve_paths(self, assets: Iterable[dict]) -> Dict[str, str]:
        """Map asset ids to on-disk paths, skipping ones not yet cached."""
        out: Dict[str, str] = {}
        for a in assets:
            digest = str(a.get("sha256") or a.get("id") or "")
            if not digest:
                continue
            path = self.path_for(digest, str(a.get("mimeType", "")), str(a.get("suggestedName", "")))
            if os.path.exists(path):
                out[str(a.get("id"))] = path
        return out

    def missing(self, assets: Iterable[dict]) -> List[str]:
        have = self.resolve_paths(assets)
        return [str(a.get("id")) for a in assets if str(a.get("id")) not in have]

    # -- maintenance -------------------------------------------------------

    def total_size(self) -> int:
        total = 0
        for dirpath, _, filenames in os.walk(self.root):
            for name in filenames:
                if name.endswith(".part"):
                    continue
                try:
                    total += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    pass
        return total

    def prune_orphans(self, referenced: Iterable[str], older_than_days: float = 30.0) -> Tuple[int, int]:
        """Delete cached assets nothing references any more.

        The age floor matters: an asset that is unreferenced right now may be
        referenced again the moment the user re-opens a project, so only files
        that have also been untouched for a while are removed. Returns
        ``(files_removed, bytes_freed)``.
        """
        keep = {r for r in referenced}
        cutoff = time.time() - older_than_days * 86400.0
        removed = freed = 0

        for dirpath, _, filenames in os.walk(self.root):
            for name in filenames:
                if name.endswith(".name"):
                    continue
                path = os.path.join(dirpath, name)
                digest = os.path.splitext(name)[0]
                if digest in keep:
                    continue
                try:
                    st = os.stat(path)
                    if st.st_mtime > cutoff:
                        continue
                    freed += st.st_size
                    os.remove(path)
                    if os.path.exists(path + ".name"):
                        os.remove(path + ".name")
                    removed += 1
                except OSError:
                    pass
        return removed, freed

    def clear(self) -> Tuple[int, int]:
        removed, freed = 0, self.total_size()
        for entry in os.listdir(self.root):
            full = os.path.join(self.root, entry)
            try:
                if os.path.isdir(full):
                    removed += sum(len(f) for _, _, f in os.walk(full))
                    shutil.rmtree(full)
                else:
                    os.remove(full)
                    removed += 1
            except OSError:
                pass
        return removed, freed
