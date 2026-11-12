"""Where screenshots and briefs live: local disk in development, a private GCS bucket in the cloud (D21).

Set LPA_BUCKET to use GCS: objects are written as gs://<bucket>/<key> and read back only through the API (the bucket
has no public access). Without it, paths are local files under runs/.
"""

from __future__ import annotations

import os
from pathlib import Path


def bucket_name() -> str | None:
    return os.environ.get("LPA_BUCKET") or None


def _bucket():
    from google.cloud import storage  # only needed in the cloud
    return storage.Client().bucket(bucket_name())


def put_file(local: str | Path, key: str, content_type: str = "image/png") -> str:
    """Upload a local file when a bucket is configured; return the reference to store (gs:// URI or local path)."""
    if not bucket_name():
        return str(local)
    _bucket().blob(key).upload_from_filename(str(local), content_type=content_type)
    return f"gs://{bucket_name()}/{key}"


def put_text(key: str, text: str, local_dir: Path) -> str:
    if not bucket_name():
        local_dir.mkdir(parents=True, exist_ok=True)
        path = local_dir / Path(key).name
        path.write_text(text)
        return str(path)
    _bucket().blob(key).upload_from_string(text, content_type="application/json")
    return f"gs://{bucket_name()}/{key}"


def read_bytes(ref: str) -> bytes | None:
    """Bytes of a stored object (gs:// URI) or local file; None if missing. Only gs:// URIs in our bucket are read."""
    if ref.startswith("gs://"):
        name, _, key = ref[5:].partition("/")
        if name != bucket_name():
            return None
        blob = _bucket().blob(key)
        return blob.download_as_bytes() if blob.exists() else None
    p = Path(ref)
    return p.read_bytes() if p.is_file() else None


def latest_text(prefix: str, local_dir: Path) -> str | None:
    """The newest object under a prefix (briefs), by name (names carry the date)."""
    if not bucket_name():
        files = sorted(local_dir.glob("*.json"))
        return files[-1].read_text() if files else None
    blobs = sorted(_bucket().list_blobs(prefix=prefix), key=lambda b: b.name)
    return blobs[-1].download_as_text() if blobs else None
