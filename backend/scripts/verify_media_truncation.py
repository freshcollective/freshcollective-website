"""Read-only check: is a candidate Media Library asset actually truncated?

Companion to ``scripts/audit_media_truncation.sql``, which finds
candidates from metadata alone. Metadata cannot distinguish a genuine
10.4 MB file from a 50 MB file cut off at 10.4 MB — both look identical
in the database. This tells them apart.

    python -m scripts.verify_media_truncation            # all candidates
    python -m scripts.verify_media_truncation --id <id>  # just one

How it decides, and why it reads so little
------------------------------------------

A truncated file is incomplete **at the end**, and every format here
carries a structural terminator there:

    PDF                      ``%%EOF`` in the trailer
    ZIP / DOCX / XLSX / PPTX end-of-central-directory record (PK\\x05\\x06)
    MP4 / MOV                the top-level box chain must span the file
    WAV                      the RIFF header's declared size must match

So the check fetches the **last 64 KB** — and for MP4, the first 64 KB
as well, to read the box chain — rather than the whole object. For a
250 MB video that is 0.05% of the file, and the bytes read are container
structure rather than creative content.

Safety
------

* **No writes of any kind.** No row is updated, no object is replaced,
  nothing is deleted. The only database statements are SELECTs.
* **Nothing is saved to disk.** Bytes are examined in memory and
  discarded.
* **Nothing is printed from the file's contents** — only the verdict,
  the filename and the size.
* Assets outside the candidate band are not touched at all.

A ``TRUNCATED`` verdict is strong evidence; an ``INTACT`` verdict means
the terminator is present and the file is very likely whole. ``UNKNOWN``
means the format has no cheap end-marker (MP3, for instance) and the
file needs a human or a decoder to judge.
"""

from __future__ import annotations

import argparse
import struct
import sys

from sqlalchemy import text

from app.core.database import SessionLocal

#: Metadata band from the SQL audit. The cap was 10,485,760 bytes for
#: the whole multipart body, so a truncated file lands just under it.
CANDIDATE_LOW = 10_400_000
CANDIDATE_HIGH = 10_485_760

#: How much of each end to read. Enough for any terminator here.
TAIL_BYTES = 64 * 1024
HEAD_BYTES = 64 * 1024


def _read_range(key: str, start: int, length: int) -> bytes | None:
    """Fetch a byte range without downloading the object.

    Uses an S3 ``Range`` request in R2 mode and a seek in filesystem
    mode. Returns None if the object cannot be read at all.
    """
    from app.core import storage

    if storage.settings.is_r2_enabled:
        try:
            resp = storage._r2_client().get_object(
                Bucket=storage._bucket_for_key(key),
                Key=key,
                Range=f"bytes={start}-{start + length - 1}",
            )
            return resp["Body"].read()
        except Exception:
            return None

    path = storage.UPLOAD_DIR / key
    if not path.is_file():
        return None
    with open(path, "rb") as fh:
        fh.seek(start)
        return fh.read(length)


def _verdict_pdf(tail: bytes) -> tuple[str, str]:
    if b"%%EOF" in tail:
        return "INTACT", "PDF trailer present"
    return "TRUNCATED", "no %%EOF — the PDF trailer is missing"


def _verdict_zip(tail: bytes) -> tuple[str, str]:
    # End-of-central-directory signature, written last by every writer.
    if b"PK\x05\x06" in tail or b"PK\x06\x06" in tail:
        return "INTACT", "central directory present"
    return "TRUNCATED", "no end-of-central-directory record"


def _verdict_mp4(head: bytes, size: int) -> tuple[str, str]:
    """Walk the top-level ISO BMFF box chain and see where it ends."""
    offset = 0
    last_box = ""
    while offset + 8 <= len(head):
        (box_size,) = struct.unpack(">I", head[offset:offset + 4])
        box_type = head[offset + 4:offset + 8].decode("latin-1", "replace")
        if box_size == 0:            # extends to end of file
            return "INTACT", f"final box '{box_type}' runs to EOF"
        if box_size == 1:            # 64-bit size follows
            if offset + 16 > len(head):
                break
            (box_size,) = struct.unpack(">Q", head[offset + 8:offset + 16])
        if box_size < 8:
            return "UNKNOWN", "malformed box header"
        last_box = box_type
        offset += box_size
        if offset > size:
            return (
                "TRUNCATED",
                f"box '{box_type}' claims {box_size:,} bytes but the file "
                f"ends at {size:,}",
            )
        if offset == size:
            return "INTACT", f"box chain ends exactly at EOF (last '{box_type}')"
    if last_box:
        return "UNKNOWN", f"box chain not resolved within the first {len(head):,} bytes"
    return "UNKNOWN", "not recognisable as ISO BMFF"


def _verdict_wav(head: bytes, size: int) -> tuple[str, str]:
    if len(head) < 12 or head[:4] != b"RIFF":
        return "UNKNOWN", "not a RIFF container"
    (declared,) = struct.unpack("<I", head[4:8])
    expected = declared + 8
    if expected == size:
        return "INTACT", "RIFF size matches the file"
    if expected > size:
        return (
            "TRUNCATED",
            f"RIFF header declares {expected:,} bytes, file is {size:,}",
        )
    return "UNKNOWN", f"RIFF declares {expected:,}, file is larger ({size:,})"


def verify(key: str, extension: str, size: int) -> tuple[str, str]:
    ext = (extension or "").lower().lstrip(".")

    if ext == "pdf":
        tail = _read_range(key, max(0, size - TAIL_BYTES), TAIL_BYTES)
        return _verdict_pdf(tail) if tail else ("UNREADABLE", "object not found")

    if ext in ("zip", "docx", "xlsx", "pptx"):
        tail = _read_range(key, max(0, size - TAIL_BYTES), TAIL_BYTES)
        return _verdict_zip(tail) if tail else ("UNREADABLE", "object not found")

    if ext in ("mp4", "mov", "m4a"):
        head = _read_range(key, 0, HEAD_BYTES)
        return _verdict_mp4(head, size) if head else ("UNREADABLE", "object not found")

    if ext == "wav":
        head = _read_range(key, 0, 12)
        return _verdict_wav(head, size) if head else ("UNREADABLE", "object not found")

    return "UNKNOWN", f"no cheap end-marker for .{ext} — needs a decoder or a human"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", help="Verify one asset id instead of the band.")
    parser.add_argument(
        "--low", type=int, default=CANDIDATE_LOW,
        help="Lower bound of the candidate band.",
    )
    parser.add_argument(
        "--high", type=int, default=CANDIDATE_HIGH,
        help="Upper bound of the candidate band.",
    )
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.id:
            rows = db.execute(text("""
                SELECT id, original_filename, extension, file_size_bytes,
                       storage_path
                  FROM creator_media_assets WHERE id = :id
            """), {"id": args.id}).all()
        else:
            rows = db.execute(text("""
                SELECT id, original_filename, extension, file_size_bytes,
                       storage_path
                  FROM creator_media_assets
                 WHERE file_size_bytes BETWEEN :lo AND :hi
                 ORDER BY created_at DESC
            """), {"lo": args.low, "hi": args.high}).all()
    finally:
        db.close()

    if not rows:
        print("No candidate assets. Nothing to verify.")
        return 0

    print(f"{len(rows)} candidate(s). Reading container structure only — "
          f"no file is downloaded in full and nothing is written.\n")
    print(f"  {'verdict':<11} {'size':>12}  {'file':<40} reason")
    counts: dict[str, int] = {}
    for asset_id, filename, ext, size, key in rows:
        verdict, reason = verify(key, ext, size)
        counts[verdict] = counts.get(verdict, 0) + 1
        shown = (filename or "")[:40]
        print(f"  {verdict:<11} {size:>12,}  {shown:<40} {reason}")

    print()
    for verdict, n in sorted(counts.items()):
        print(f"  {verdict}: {n}")
    if counts.get("TRUNCATED"):
        print("\n  TRUNCATED assets cannot be repaired from here — the missing")
        print("  bytes were never stored. The affected creators need to")
        print("  re-upload; the release fixes the cause so a re-upload works.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
