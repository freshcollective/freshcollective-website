"""Receive an upload onto disk without putting it in the heap.

Extracted from ``offering_upload`` so the three pre-existing
large-file endpoints can use the same mechanism the Offerings upload
path already uses. Those three — the Media Library, Collective
resources, and Pathway step resources — each call ``await file.read()``
and hold the whole upload in memory, which on a 512 MB instance is
survivable for a 10 MB document and is not for the 250 MB video the
Media Library advertises.

Why this had not bitten anyone yet
----------------------------------

It had, invisibly. Next.js was truncating every proxied body over
10 MiB before it reached fc-api (see ``next.config.ts`` and the B6/B7
report), so a 250 MB video arrived as 10 MiB of corrupt data and
``file.read()`` only ever allocated that much. Fixing the truncation is
what makes the memory exposure real, which is why the two changes belong
in the same release.

What this does not decide
-------------------------

Nothing about *policy*: no extension list, no per-type ceiling, no
message. The caller passes the byte limit it has already decided on and
maps :class:`UploadTooLarge` to whatever its surface says. That is what
lets the Offerings path keep its plan-aware wording while the Media
Library keeps "File exceeds the 250 MB limit for video files."
"""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from fastapi import UploadFile

#: Copy granularity. One megabyte is large enough that the syscall
#: overhead is irrelevant and small enough that peak resident bytes per
#: in-flight upload stay flat regardless of file size.
CHUNK_BYTES = 1024 * 1024


class UploadTooLarge(Exception):
    """The body exceeded ``max_bytes`` while being received.

    Raised **during** the copy, so an oversized upload is abandoned
    part-way rather than written out in full and measured afterwards.
    """

    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"upload exceeded {max_bytes} bytes")
        self.max_bytes = max_bytes


class EmptyUpload(Exception):
    """Nothing arrived."""


@dataclass
class SpooledUpload:
    """An upload on local disk, measured."""

    path: str
    byte_size: int
    filename: str
    content_type: str | None

    def open(self):
        """A binary stream at position 0, for handing to a transfer."""
        return open(self.path, "rb")


@contextmanager
def stream_to_temp(
    upload: UploadFile, *, max_bytes: int, prefix: str = "fc-upload-",
) -> Iterator[SpooledUpload]:
    """Copy ``upload`` to a temporary file in bounded chunks.

    Always removes the temporary file on the way out — success, refusal
    or exception alike. That single ``finally`` is the whole answer to
    "are temporary files cleaned up": there is one exit, not a success
    path and a failure path that must be kept in step.

    Raises :class:`UploadTooLarge` as soon as the limit is passed and
    :class:`EmptyUpload` if nothing arrived.
    """
    source = upload.file
    try:
        source.seek(0)
    except (OSError, ValueError):   # pragma: no cover — unseekable stream
        pass

    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".upload")
    size = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = source.read(CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise UploadTooLarge(max_bytes)
                out.write(chunk)
        if size == 0:
            raise EmptyUpload()
        yield SpooledUpload(
            path=path,
            byte_size=size,
            filename=upload.filename or "upload",
            content_type=upload.content_type,
        )
    finally:
        try:
            os.unlink(path)
        except OSError:   # pragma: no cover — already gone
            pass


__all__ = [
    "CHUNK_BYTES",
    "UploadTooLarge",
    "EmptyUpload",
    "SpooledUpload",
    "stream_to_temp",
]
