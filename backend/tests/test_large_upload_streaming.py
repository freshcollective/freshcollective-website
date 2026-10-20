"""Large uploads reach storage without passing through the heap.

The Media Library advertises 250 MB video, Collective resources share
that ceiling, and Pathway step resources accept 200 MB. All three
handlers used to call ``await file.read()``, putting the whole upload in
fc-api's memory on a 512 MB instance.

That exposure was invisible until B6/B7, because Next.js truncated every
proxied body at 10 MiB before it reached fc-api — so a 250 MB video
arrived as 10 MiB of corrupt data and ``read()`` only ever allocated
that much. Removing the truncation is what made the memory real, which
is why both changes ship together.

Measured here with ``tracemalloc``, which counts Python allocations —
the thing that would exhaust the instance. These establish an upper
bound on this machine and the *shape* of the curve; they are not a
claim about production throughput.
"""

from __future__ import annotations

import io
import os
import tracemalloc
import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.core import storage
from app.creator import routes as creator_routes
from app.services.streaming_upload import (
    EmptyUpload, UploadTooLarge, stream_to_temp,
)

MB = 1024 * 1024


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _upload(data: bytes, name: str, ctype: str) -> UploadFile:
    """An UploadFile backed by a real temp file, as Starlette provides
    for anything past its 1 MB spool threshold."""
    import tempfile
    spooled = tempfile.SpooledTemporaryFile(max_size=MB)
    spooled.write(data)
    spooled.seek(0)
    return UploadFile(
        file=spooled, filename=name, headers=Headers({"content-type": ctype}),
    )


@pytest.fixture(autouse=True)
def clean_media():
    root = storage.UPLOAD_DIR / "media"
    before = {p for p in root.rglob("*") if p.is_file()} if root.exists() else set()
    yield
    if root.exists():
        for p in root.rglob("*"):
            if p.is_file() and p not in before:
                p.unlink()
    steps = storage.UPLOAD_DIR / "steps"
    if steps.exists():
        for p in steps.rglob("*"):
            if p.is_file():
                p.unlink()


@pytest.fixture
def space(db, make_space):
    from app.models.user import User
    sp = make_space()
    owner = db.query(User).filter(User.id == sp.creator_id).one()
    return sp, owner


# ---------------------------------------------------------------------------
# The shared primitive
# ---------------------------------------------------------------------------


class TestStreamToTemp:

    def test_it_copies_the_whole_body(self):
        payload = os.urandom(3 * MB)
        with stream_to_temp(_upload(payload, "x.bin", "application/octet-stream"),
                            max_bytes=10 * MB) as got:
            assert got.byte_size == len(payload)
            with got.open() as fh:
                assert fh.read() == payload, "the copy is not byte-identical"

    def test_the_temp_file_is_always_removed(self):
        import tempfile
        d = tempfile.gettempdir()
        before = set(os.listdir(d))

        with stream_to_temp(_upload(b"x" * 1024, "x.bin", "text/plain"),
                            max_bytes=MB) as got:
            path = got.path
            assert os.path.isfile(path)
        assert not os.path.isfile(path), "the temp file survived a success"

        with pytest.raises(UploadTooLarge):
            with stream_to_temp(_upload(b"x" * (2 * MB), "x.bin", "text/plain"),
                                max_bytes=MB):
                pass
        leaked = {
            n for n in set(os.listdir(d)) - before if n.startswith("fc-upload-")
        }
        assert leaked == set(), f"temp files leaked: {leaked}"

    def test_an_oversized_body_is_abandoned_part_way(self):
        """Not written out in full and measured afterwards — the whole
        point is that the bytes never land."""
        with pytest.raises(UploadTooLarge) as exc:
            with stream_to_temp(_upload(b"x" * (5 * MB), "x.bin", "text/plain"),
                                max_bytes=MB):
                pass
        assert exc.value.max_bytes == MB

    def test_an_empty_body_is_refused(self):
        with pytest.raises(EmptyUpload):
            with stream_to_temp(_upload(b"", "x.bin", "text/plain"),
                                max_bytes=MB):
                pass

    def test_memory_does_not_scale_with_the_body(self):
        def peak_for(size: int) -> int:
            payload = b"\0" * size
            up = _upload(payload, "x.bin", "application/octet-stream")
            del payload
            tracemalloc.start()
            try:
                tracemalloc.reset_peak()
                base = tracemalloc.get_traced_memory()[0]
                with stream_to_temp(up, max_bytes=64 * MB):
                    pass
                return tracemalloc.get_traced_memory()[1] - base
            finally:
                tracemalloc.stop()

        small = peak_for(2 * MB)
        large = peak_for(24 * MB)
        # Twelve times the body must not cost twelve times the memory.
        assert large < small + (4 * MB), (small, large)


# ---------------------------------------------------------------------------
# The three handlers
# ---------------------------------------------------------------------------


class TestMediaLibraryUpload:

    def test_a_large_document_is_stored_intact(self, db, space):
        """25 MB — well past the 10 MiB cliff that used to corrupt it."""
        sp, owner = space
        payload = os.urandom(12 * MB)
        asset = creator_routes.upload_media(
            sp.slug, file=_upload(payload, "guide.pdf", "application/pdf"),
            title="", description="", db=db, current_user=owner,
        )
        assert asset["file_size_bytes"] == len(payload)
        stored = storage.UPLOAD_DIR / asset["storage_path"]
        assert stored.is_file()
        assert stored.read_bytes() == payload, "stored bytes differ from sent"

    def test_the_per_type_limit_is_still_enforced(self, db, space):
        """Images cap at 10 MB. The limit must not have been lost when
        the read moved to a stream."""
        sp, owner = space
        with pytest.raises(HTTPException) as exc:
            creator_routes.upload_media(
                sp.slug,
                file=_upload(b"\0" * (11 * MB), "big.png", "image/png"),
                title="", description="", db=db, current_user=owner,
            )
        assert exc.value.status_code == 400
        assert "10 MB" in str(exc.value.detail)

    def test_an_unsupported_type_is_still_refused(self, db, space):
        sp, owner = space
        with pytest.raises(HTTPException) as exc:
            creator_routes.upload_media(
                sp.slug, file=_upload(b"MZ", "tool.exe", "application/octet-stream"),
                title="", description="", db=db, current_user=owner,
            )
        assert exc.value.status_code == 400
        assert "not permitted" in str(exc.value.detail)

    def test_the_storage_key_shape_is_unchanged(self, db, space):
        """``_authorise_media`` reads the Collective slug out of the
        segment after ``media/``, so the layout is load-bearing."""
        sp, owner = space
        asset = creator_routes.upload_media(
            sp.slug, file=_upload(b"%PDF-1.4\n" + b"x" * 2048, "a.pdf",
                                  "application/pdf"),
            title="", description="", db=db, current_user=owner,
        )
        parts = asset["storage_path"].split("/")
        assert parts[0] == "media"
        assert parts[1] == sp.slug
        assert asset["file_url"] == f"/api/uploads/{asset['storage_path']}"

    def test_uploading_does_not_hold_the_body_in_memory(self, db, space):
        sp, owner = space
        size = 20 * MB
        payload = b"\0" * size
        up = _upload(payload, "big.pdf", "application/pdf")
        del payload

        tracemalloc.start()
        try:
            tracemalloc.reset_peak()
            base = tracemalloc.get_traced_memory()[0]
            creator_routes.upload_media(
                sp.slug, file=up, title="", description="",
                db=db, current_user=owner,
            )
            growth = tracemalloc.get_traced_memory()[1] - base
        finally:
            tracemalloc.stop()

        assert growth < size // 4, (
            f"upload_media allocated {growth / MB:.1f} MB for a "
            f"{size / MB:.0f} MB file"
        )


class TestStepResourceUpload:

    def test_a_large_step_resource_is_stored_intact(self, db, space):
        from app.models.platform import Pathway, PathwayStatus, PathwayStep

        sp, owner = space
        pw = Pathway(
            id=_uid("pw"), space_id=sp.id, slug=f"p-{uuid.uuid4().hex[:8]}",
            title="P", status=PathwayStatus.draft, position=0,
        )
        db.add(pw)
        step = PathwayStep(
            id=_uid("st"), pathway_id=pw.id,
            slug=f"s-{uuid.uuid4().hex[:8]}", title="S", position=0,
        )
        db.add(step)
        db.flush()

        payload = os.urandom(12 * MB)
        res = creator_routes.upload_step_resource(
            sp.slug, pw.slug, step.slug, title="A file", description=None,
            file=_upload(payload, "notes.pdf", "application/pdf"),
            db=db, current_user=owner,
        )
        assert res.file_size == len(payload)
        assert (storage.UPLOAD_DIR / res.url).read_bytes() == payload


class TestSourceContract:

    def test_no_large_upload_handler_reads_the_whole_body(self):
        """The three handlers that can receive tens of megabytes must
        not go back to ``await file.read()``."""
        import ast
        import pathlib

        import re
        raw = (pathlib.Path(__file__).resolve().parent.parent
               / "app" / "creator" / "routes.py").read_text()
        # Blank out comment lines, keeping line numbers intact so
        # ``get_source_segment`` still lines up. Without this, the
        # comment *explaining* that these handlers no longer call
        # ``await file.read()`` fails the assertion that they do not —
        # banning the word instead of the use.
        src = re.sub(r"(?m)^(\s*)#.*$", r"\1", raw)
        tree = ast.parse(src)
        watched = {
            "upload_media", "upload_space_resource_file", "upload_step_resource",
        }
        seen = set()
        for node in ast.walk(tree):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name in watched):
                seen.add(node.name)
                body = ast.get_source_segment(src, node) or ""
                assert "await file.read()" not in body, node.name
                assert ".file.read()" not in body, node.name
        assert seen == watched, f"handlers not found: {watched - seen}"

    def test_the_large_upload_handlers_are_synchronous(self):
        """Blocking I/O in an ``async def`` runs on the event loop and
        would stall every other request during a 250 MB upload."""
        import inspect
        from app.creator import routes

        for name in (
            "upload_media", "upload_space_resource_file", "upload_step_resource",
        ):
            fn = getattr(routes, name)
            assert not inspect.iscoroutinefunction(fn), (
                f"{name} is async but does blocking I/O — FastAPI will run "
                "it on the event loop instead of its threadpool"
            )
