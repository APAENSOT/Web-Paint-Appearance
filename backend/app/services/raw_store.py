"""Where the uploaded bytes live.

`02-PIPELINE.md` §1: the file is hashed, stored under its own hash, and every
later step -- cleaning, replay after an alias is approved, re-reading a batch
at commit -- reads *those* bytes back. Nobody is ever asked to re-send a file
because the platform lost its copy.

Locally that is a directory (`data/raw/`, gitignored). In GCP it is Cloud
Storage with object versioning, keyed the same way
(`00-ARCHITECTURE.md` §3.2). Only this module knows which, so the swap is one
class rather than a change everywhere a batch is read.

Content-addressed storage has a property worth stating: writing the same
bytes twice is a no-op, so a retried upload cannot corrupt an existing
object, and an object can never disagree with the hash that names it.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

#: The `load_batch.raw_store_key` convention T02 established.
KEY_PREFIX = "wavescan/raw/"


def key_for(file_hash: str) -> str:
    return f"{KEY_PREFIX}{file_hash}"


class RawStore:
    """A content-addressed blob store backed by the local filesystem."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # -----------------------------------------------------------------
    def path_for(self, key: str) -> Path:
        if not key.startswith(KEY_PREFIX):
            raise ValueError(f"not a raw-store key: {key!r}")
        name = key[len(KEY_PREFIX):]
        # The key is a SHA-256 hex digest produced by this application. Check
        # it anyway: this value reaches a filesystem path, and a key read back
        # from a row someone else wrote must not be able to escape the root.
        if len(name) != 64 or any(c not in "0123456789abcdef" for c in name):
            raise ValueError(f"not a sha-256 key: {key!r}")
        return self.root / name

    def exists(self, key: str) -> bool:
        return self.path_for(key).is_file()

    def put(self, file_hash: str, data: bytes) -> str:
        """Store bytes under their hash and return the key.

        Written to a temporary file and renamed, so a reader never sees a
        half-written object and a crash mid-write leaves no truncated blob
        that would later be parsed as a workbook.
        """
        key = key_for(file_hash)
        target = self.path_for(key)
        if target.is_file():
            return key
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".incoming-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return key

    def get(self, key: str) -> bytes:
        path = self.path_for(key)
        if not path.is_file():
            raise FileNotFoundError(
                f"raw object {key} is missing from {self.root}. The batch that "
                f"references it cannot be replayed or committed until it is "
                f"restored."
            )
        return path.read_bytes()

    def health(self) -> dict:
        """Reported by /health/ready: configured, present, and writable."""
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            probe = self.root / ".write-probe"
            probe.write_bytes(b"")
            probe.unlink()
        except OSError as exc:
            return {
                "status": "down",
                "detail": f"{self.root} is not writable: {exc.__class__.__name__}",
            }
        return {"status": "ok", "backend": "filesystem", "path": str(self.root)}
