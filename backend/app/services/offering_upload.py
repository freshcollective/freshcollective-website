"""Receiving an Offering file without holding it in memory.

Phase B5, and the constraint that shapes all of it: fc-api runs on a
Render Starter instance — 0.5 CPU, 512 MB RAM. A 50 MB upload handled
the way every other upload surface in this platform handles one
(``data = file.file.read()``, see ``upload_step_resource``) puts the
whole file in the Python heap, and three concurrent uploads put 150 MB
there before boto3 has copied a byte.

So nothing here ever reads a whole file. Three mechanisms, in the order
a request meets them:

  1. **A Content-Length precheck**, in middleware, refuses an oversized
     body *before* Starlette parses it. See
     ``app.main.limit_offering_upload_size`` — it has to be middleware,
     because FastAPI parses the multipart body before it resolves a
     route's dependencies, so a ``Depends`` would run too late to help.
  2. **A concurrency slot**, so the number of in-flight uploads is
     bounded by configuration rather than by how many creators happen to
     press Upload at once.
  3. **Disk-backed streaming**, start to finish. Starlette has already
     spooled the body past 1 MB to a temporary file on disk, and this
     module hands that same file object to boto3's multipart transfer
     rather than copying it through a buffer. Peak resident bytes per
     upload is one transfer chunk per part thread, not one file.

What this module deliberately does not do
-----------------------------------------

It does not validate contents. Structural validation is the worker's
job (``offering_validation_worker``), runs outside the request, and is
the only thing that can move a file to ``passed``. This module decides
whether an upload may be *stored*; it never decides whether it may be
*downloaded*.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from fastapi import HTTPException, UploadFile, status

from app.services.offering_validation import InspectionBudget

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

#: Simultaneous Offering uploads this process will accept.
#:
#: Two, on a 0.5-CPU instance. Each in-flight upload costs one
#: Starlette temp file on disk plus boto3's bounded in-flight parts
#: (~24 MB at the configured 8 MB × 3), so two is ~48 MB of transfer
#: buffers on a 512 MB box — leaving the rest for ordinary request
#: handling, which must not degrade because somebody is uploading.
#:
#: This is a per-process bound, not a cluster-wide one. With one
#: instance that is the same thing; with several, each gets two, which
#: is the correct scaling behaviour for a limit that exists to protect
#: an individual process's memory.
MAX_CONCURRENT_UPLOADS = 2

_slots = threading.BoundedSemaphore(MAX_CONCURRENT_UPLOADS)


@contextmanager
def upload_slot() -> Iterator[None]:
    """Hold one of the concurrency slots, or refuse the request.

    Non-blocking. A creator who arrives when both slots are busy is told
    to try again in a moment rather than being parked on a worker thread
    — queueing here would hold a thread from the pool that serves every
    other request, which is the opposite of protecting the API.

    **429, not 503.** The request is being shed deliberately, and 503
    would be captured as a Sentry event: ``StarletteIntegration`` keeps
    its ``failed_request_status_codes`` default of 500–599, which is how
    FC-API-9 came to hold 36 events of the system working as designed.
    429 also carries the right meaning for a client — retry — where 503
    suggests the service is down.
    """
    if not _slots.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "reason": "upload_busy",
                "message": (
                    "We're handling other uploads right now. Please try "
                    "again in a moment — nothing has been lost."
                ),
            },
        )
    try:
        yield
    finally:
        _slots.release()


# ---------------------------------------------------------------------------
# Receiving
# ---------------------------------------------------------------------------


@dataclass
class ReceivedUpload:
    """An upload on local disk, measured but not yet stored or inspected."""

    path: str
    byte_size: int
    #: Downloadable resources this upload contributes. See
    #: :func:`count_resources`.
    resource_count: int
    filename: str
    content_type: str | None

    def open(self):
        """A binary stream at position 0, for handing to the transfer."""
        return open(self.path, "rb")


@contextmanager
def received(
    upload: UploadFile, *, max_bytes: int,
) -> Iterator[ReceivedUpload]:
    """Materialise ``upload`` on local disk and measure it.

    Yields a :class:`ReceivedUpload`; always removes the temporary file
    on the way out, whether the caller succeeded, refused the upload or
    raised. That ``finally`` is the whole answer to "temporary files are
    cleaned up": there is no success path and no failure path, only one
    exit.

    ``max_bytes`` is enforced **as the bytes are copied**, so an
    oversized upload is abandoned part-way instead of being written out
    in full and measured afterwards. The middleware precheck will
    normally have refused it already; this is the backstop for a client
    that sent no Content-Length or lied about it, and the one that is
    actually authoritative because it counts what arrived.
    """
    src = upload.file
    try:
        src.seek(0)
    except (OSError, ValueError):   # pragma: no cover — unseekable stream
        pass

    fd, path = tempfile.mkstemp(prefix="fc-offering-", suffix=".upload")
    size = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    # Stop here. Nothing is stored, nothing is charged,
                    # and the partial temp file goes in the ``finally``.
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail={
                            "reason": "file_too_large",
                            "message": (
                                "That file is larger than your plan allows."
                            ),
                        },
                    )
                out.write(chunk)

        if size == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"reason": "empty_file", "message": "That file is empty."},
            )

        yield ReceivedUpload(
            path=path,
            byte_size=size,
            resource_count=count_resources(path, upload.filename or ""),
            filename=upload.filename or "upload",
            content_type=upload.content_type,
        )
    finally:
        try:
            os.unlink(path)
        except OSError:   # pragma: no cover — already gone
            pass


# ---------------------------------------------------------------------------
# Resource counting
# ---------------------------------------------------------------------------

#: Extensions that are ZIP containers but are *one* resource: an Office
#: package's internal parts are machinery a reader consumes, not files a
#: member receives. Counting them would charge a creator twenty
#: resources for one spreadsheet.
_OOXML = {".docx", ".xlsx", ".pptx"}


def count_resources(path: str, filename: str) -> int:
    """How many downloadable resources this file contributes.

    One for a plain file. One for an Office package. For a ``.zip``, the
    number of non-directory entries — which is what stops an archive
    being a way around the file allowance.

    Reads the archive's **central directory** only: no decompression, no
    member reads, bounded by the same ``max_entries`` the inspection
    budget uses. That is cheap enough to do inside the request, and
    doing it there is what lets the limit be enforced at upload rather
    than discovered later by the worker.

    An unreadable archive is refused here rather than counted as one
    resource. The worker would reject it anyway, but between now and then
    it would be holding a slot under a count we know to be wrong.
    """
    ext = os.path.splitext(filename.lower())[1]
    if ext in _OOXML:
        return 1
    if ext != ".zip":
        return 1

    budget = InspectionBudget()
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > budget.max_entries:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "reason": "too_many_entries",
                        "message": (
                            f"This archive contains more than "
                            f"{budget.max_entries} files. Please split it "
                            "into smaller downloads."
                        ),
                    },
                )
            return max(1, sum(1 for i in infos if not i.is_dir()))
    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "reason": "unreadable",
                "message": (
                    "We couldn't read this ZIP — it may not have uploaded "
                    "completely. Please try again."
                ),
            },
        ) from exc


__all__ = [
    "MAX_CONCURRENT_UPLOADS",
    "ReceivedUpload",
    "upload_slot",
    "received",
    "count_resources",
]
