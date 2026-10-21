"""Offerings Phase B — content validation, ZIP inspection, quarantine.

Two things make this file trustworthy rather than merely green.

**Genuine fixtures.** ``tests/fixtures/offerings/`` holds real
LibreOffice output — a true ``.docx``, ``.xlsx``, ``.pptx`` and
``.xlsm``. Hand-rolled "ZIP-like" bytes would certify a parser that
real Office documents fail, which is the exact regression this feature
could ship. Every "normal document still works" test runs against the
real thing.

**Positive controls beside every refusal.** Each rejection test sits
next to one proving the legitimate case passes. A validator that
refused everything would satisfy half this file; it would fail the
other half.

Nothing here touches Stripe, production data or the network.
"""

from __future__ import annotations

import io
import pathlib
import uuid
import zipfile
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.offering import (
    Offering,
    OfferingEntitlement,
    OfferingEntitlementSource,
    OfferingEntitlementStatus,
    OfferingFile,
    OfferingFileValidationStatus as VS,
    OfferingStatus,
)
from app.models.platform import SpaceMembership, SpaceMembershipStatus
from app.services import offering_files as of
from app.services import offering_validation as ov
from app.services import offering_file_validation_service as svc
from app.uploads.authorization import authorize_upload

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "offerings"

OOXML_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:16]}"


def genuine(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def pdf(body: bytes = b"stream content") -> bytes:
    return b"%PDF-1.7\n" + body + b"\ntrailer\n%%EOF\n"


def mp4(brand: bytes = b"isom") -> bytes:
    """A real ISO-BMFF ftyp box. The brand is the video/audio signal."""
    return b"\x00\x00\x00\x20ftyp" + brand + b"\x00\x00\x02\x00" + b"\x00" * 16


def m4a() -> bytes:
    return mp4(b"M4A ")


def mp3() -> bytes:
    return b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" + b"\x00" * 64


def wav(samples: int = 64) -> bytes:
    """A genuinely valid RIFF/WAVE PCM file."""
    data = b"\x00\x00" * samples
    fmt = (b"fmt " + (16).to_bytes(4, "little") + (1).to_bytes(2, "little")
           + (1).to_bytes(2, "little") + (44100).to_bytes(4, "little")
           + (88200).to_bytes(4, "little") + (2).to_bytes(2, "little")
           + (16).to_bytes(2, "little"))
    chunks = fmt + b"data" + len(data).to_bytes(4, "little") + data
    return b"RIFF" + (len(chunks) + 4).to_bytes(4, "little") + b"WAVE" + chunks


def zip_of(entries: dict[str, bytes], **kw) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, payload in entries.items():
            z.writestr(name, payload, **kw)
    return buf.getvalue()


def run(name: str, data: bytes, ctype: str | None = None, **kw):
    """Validate one file, inferring a plausible declared type."""
    ext = of.all_extensions(name)[-1]
    if ctype is None:
        allowed = of.OFFERING_ALLOWED_TYPES.get(ext)
        ctype = sorted(allowed)[0] if allowed else "application/octet-stream"
    return svc.validate_bytes(
        filename=name, declared_type=ctype, data=data, **kw,
    )


# ---------------------------------------------------------------------------
# 1 · Genuine documents still work  (the regression that matters most)
# ---------------------------------------------------------------------------


class TestGenuineFilesPass:
    @pytest.mark.parametrize("name", ["genuine.docx", "genuine.xlsx", "genuine.pptx"])
    def test_real_office_documents_pass(self, name):
        """Real LibreOffice output. These are ZIP archives full of
        compressed XML, and a type-blind archive policy would reject
        them — which would make Offerings useless for templates."""
        ext = pathlib.Path(name).suffix
        r = run(name, genuine(name), OOXML_TYPES[ext])
        assert r.status == VS.passed.value, (r.reason, r.message)

    def test_real_office_compression_is_far_under_the_ratio_ceiling(self):
        """Evidence the 200:1 ceiling is safe for legitimate files
        rather than merely asserted to be."""
        for name in ("genuine.docx", "genuine.xlsx", "genuine.pptx"):
            z = zipfile.ZipFile(io.BytesIO(genuine(name)))
            for i in z.infolist():
                if i.compress_size:
                    assert i.file_size / i.compress_size < 200

    @pytest.mark.parametrize("name,data", [
        ("workbook.pdf", pdf()),
        ("meditation.mp3", mp3()),
        ("reading.m4a", m4a()),
        ("tone.wav", wav()),
        ("notes.txt", b"Plain notes for members.\n"),
        ("notes.md", b"# Heading\n\nSome guidance.\n"),
    ])
    def test_other_allowed_formats_pass(self, name, data):
        r = run(name, data)
        assert r.status == VS.passed.value, (r.reason, r.message)

    def test_a_legitimate_zip_bundle_passes(self):
        data = zip_of({
            "guide.pdf": pdf(),
            "audio/track.mp3": mp3(),
            "sheet.xlsx": genuine("genuine.xlsx"),
            "readme.txt": b"Thank you for your purchase.\n",
        })
        r = run("bundle.zip", data)
        assert r.status == VS.passed.value, (r.reason, r.message)

    def test_a_passing_file_records_every_required_check(self):
        r = run("workbook.pdf", pdf())
        ids = {c.id for c in r.checks if c.outcome == "pass"}
        assert ov.required_check_ids() <= ids
        assert r.policy_version == ov.VALIDATION_POLICY_VERSION


# ---------------------------------------------------------------------------
# 2 · Content-based identification
# ---------------------------------------------------------------------------


class TestSignatureAgreement:
    def test_an_executable_renamed_as_a_document_is_refused(self):
        """The Phase A gap. Extension and declared type both say PDF;
        only the bytes disagree."""
        r = run("workbook.pdf", b"MZ\x90\x00" + b"\x00" * 200, "application/pdf")
        assert r.status == VS.rejected.value
        assert r.reason == "forbidden_type"

    def test_an_elf_binary_renamed_as_audio_is_refused(self):
        r = run("track.mp3", b"\x7fELF\x02\x01\x01" + b"\x00" * 200)
        assert r.status == VS.rejected.value

    def test_a_video_renamed_as_a_pdf_is_refused_as_video(self):
        """Named ``.pdf``, declared ``application/pdf``, actually MP4.
        The message must still be the video one, because that is what
        the creator needs to hear."""
        r = run("holiday.pdf", mp4(), "application/pdf")
        assert r.status == VS.rejected.value
        assert r.reason == "video_detected"
        assert "video" in r.message.lower()

    def test_a_video_renamed_as_audio_is_refused(self):
        """``.m4a`` and MP4 share a container; only the brand differs,
        which is why brand detection and not extension is the gate."""
        r = run("lesson.m4a", mp4(b"isom"))
        assert r.status == VS.rejected.value
        assert r.reason == "video_detected"

    def test_genuine_m4a_audio_still_passes(self):
        """The positive control for the test above — without it, the
        video gate could be rejecting all ISO-BMFF files."""
        assert run("lesson.m4a", m4a()).status == VS.passed.value

    def test_a_zip_renamed_as_a_pdf_is_refused(self):
        r = run("guide.pdf", zip_of({"a.txt": b"x"}), "application/pdf")
        assert r.status == VS.rejected.value
        assert r.reason == "signature_mismatch"

    def test_a_pdf_renamed_as_a_spreadsheet_is_refused(self):
        r = run("budget.xlsx", pdf(), OOXML_TYPES[".xlsx"])
        assert r.status == VS.rejected.value
        assert r.reason == "signature_mismatch"

    def test_a_binary_renamed_as_text_is_refused(self):
        """Text has no signature, so the rule inverts: it must not
        match anything else."""
        r = run("notes.txt", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        assert r.status == VS.rejected.value
        assert r.reason == "signature_mismatch"

    def test_a_double_extension_is_refused_on_its_inner_suffix(self):
        r = run("invoice.pdf.exe", pdf(), "application/pdf")
        assert r.status == VS.rejected.value
        assert r.reason == "forbidden_type"

    def test_a_declared_type_that_disagrees_is_refused(self):
        r = run("guide.pdf", pdf(), "application/zip")
        assert r.status == VS.rejected.value
        assert r.reason == "content_type_mismatch"


class TestOfficePolicy:
    def test_macro_enabled_extensions_are_refused_by_name(self):
        """Genuine LibreOffice .xlsm. Named rather than merely
        unlisted, so the message can tell the creator what to do."""
        r = run("budget.xlsm", genuine("genuine.xlsm"), OOXML_TYPES[".xlsx"])
        assert r.status == VS.rejected.value
        assert r.reason == "macro_document"
        assert ".xlsx" in r.message

    def test_a_macro_project_hidden_in_an_xlsx_is_refused(self):
        """A macro workbook renamed ``.xlsx``. No extension check can
        see this — only opening the package can. Built by injecting
        into a *genuine* xlsx so the base is real."""
        src = zipfile.ZipFile(io.BytesIO(genuine("genuine.xlsx")))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
            for i in src.infolist():
                out.writestr(i, src.read(i.filename))
            out.writestr("xl/vbaProject.bin", b"\xd0\xcf\x11\xe0fake-vba")
        r = run("budget.xlsx", buf.getvalue(), OOXML_TYPES[".xlsx"])
        assert r.status == VS.rejected.value
        assert r.reason == "macro_document"

    @pytest.mark.parametrize("name", ["old.doc", "old.xls", "old.ppt"])
    def test_legacy_office_extensions_are_refused(self, name):
        r = run(name, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 200,
                "application/msword")
        assert r.status == VS.rejected.value
        assert r.reason == "legacy_office"

    def test_legacy_office_removed_from_the_allow_list(self):
        for ext in (".doc", ".xls", ".ppt"):
            assert ext not in of.OFFERING_ALLOWED_TYPES, ext

    def test_rtf_and_epub_are_out_of_phase_one(self):
        for ext in (".rtf", ".epub"):
            assert ext not in of.OFFERING_ALLOWED_TYPES, ext

    def test_txt_and_md_are_kept(self):
        for ext in (".txt", ".md"):
            assert ext in of.OFFERING_ALLOWED_TYPES, ext

    def test_an_ole2_file_renamed_as_a_pdf_is_refused(self):
        r = run("guide.pdf", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64,
                "application/pdf")
        assert r.status == VS.rejected.value
        assert r.reason == "legacy_office"


class TestStructure:
    def test_a_truncated_pdf_is_refused(self):
        r = run("guide.pdf", b"%PDF-1.7\nbody with no trailer", "application/pdf")
        assert r.status == VS.rejected.value
        assert r.reason == "unreadable"

    def test_a_corrupt_ooxml_package_is_refused(self):
        """Valid ZIP, but not an Office document."""
        r = run("budget.xlsx", zip_of({"random.txt": b"x"}), OOXML_TYPES[".xlsx"])
        assert r.status == VS.rejected.value
        assert r.reason in ("unreadable", "signature_mismatch")

    def test_truncated_zip_bytes_are_refused(self):
        r = run("bundle.zip", zip_of({"a.pdf": pdf()})[:40])
        assert r.status == VS.rejected.value


# ---------------------------------------------------------------------------
# 3 · ZIP inspection
# ---------------------------------------------------------------------------


class TestZipInspection:
    def test_a_video_inside_is_refused(self):
        r = run("bundle.zip", zip_of({"guide.pdf": pdf(), "clip.mp4": mp4()}))
        assert r.status == VS.rejected.value
        assert r.reason == "zip_contents"

    def test_a_video_with_a_misleading_extension_inside_is_refused(self):
        """The case extension checks cannot catch: an MP4 named
        ``holiday.pdf`` inside the bundle."""
        r = run("bundle.zip", zip_of({"holiday.pdf": mp4()}))
        assert r.status == VS.rejected.value
        assert r.reason == "zip_video"

    def test_an_executable_inside_is_refused(self):
        r = run("bundle.zip", zip_of({"setup.exe": b"MZ\x90\x00"}))
        assert r.status == VS.rejected.value
        assert r.reason == "zip_executable"

    def test_an_executable_with_a_document_name_inside_is_refused(self):
        r = run("bundle.zip", zip_of({"readme.pdf": b"MZ\x90\x00" + b"\x00" * 99}))
        assert r.status == VS.rejected.value
        assert r.reason == "zip_executable"

    def test_a_script_inside_is_refused(self):
        r = run("bundle.zip", zip_of({"install.sh": b"#!/bin/sh\nrm -rf /\n"}))
        assert r.status == VS.rejected.value

    def test_a_nested_zip_is_refused(self):
        r = run("bundle.zip", zip_of({
            "guide.pdf": pdf(), "more.zip": zip_of({"x.pdf": pdf()}),
        }))
        assert r.status == VS.rejected.value
        assert r.reason == "nested_zip"

    def test_a_nested_office_document_is_allowed(self):
        """The counterpart that stops the nested-archive rule from
        rejecting legitimate bundles — a DOCX *is* a ZIP."""
        r = run("bundle.zip", zip_of({"notes.docx": genuine("genuine.docx")}))
        assert r.status == VS.passed.value, (r.reason, r.message)

    def test_a_macro_file_hidden_in_a_nested_office_document_is_refused(self):
        """One level of nested package inspection, so an .xlsm cannot
        ride inside a .zip by being renamed .xlsx."""
        src = zipfile.ZipFile(io.BytesIO(genuine("genuine.xlsx")))
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as out:
            for i in src.infolist():
                out.writestr(i, src.read(i.filename))
            out.writestr("xl/vbaProject.bin", b"fake")
        r = run("bundle.zip", zip_of({"budget.xlsx": inner.getvalue()}))
        assert r.status == VS.rejected.value
        assert r.reason in ("zip_contents", "macro_document")

    def test_an_encrypted_archive_is_refused(self):
        """Python's zipfile cannot *write* an encrypted archive, so the
        general-purpose bit flag is set directly — in the central
        directory as well as the local headers, because that is the copy
        ``infolist()`` reports and therefore the one the inspector
        reads. This is the same bit a real password-protected archive
        sets."""
        raw = bytearray(zip_of({"guide.pdf": pdf(), "notes.txt": b"hi"}))
        # Local file header: signature PK\x03\x04, flags at +6.
        i = 0
        while (i := raw.find(b"PK\x03\x04", i)) != -1:
            raw[i + 6] |= 0x01
            i += 4
        # Central directory record: signature PK\x01\x02, flags at +8.
        i = 0
        while (i := raw.find(b"PK\x01\x02", i)) != -1:
            raw[i + 8] |= 0x01
            i += 4
        data = bytes(raw)
        assert any(
            inf.flag_bits & 0x1
            for inf in zipfile.ZipFile(io.BytesIO(data)).infolist()
        ), "fixture must actually be flagged encrypted"
        r = run("bundle.zip", data)
        assert r.status == VS.rejected.value
        assert r.reason == "encrypted_archive"
        assert "password-protected" in r.message

    def test_a_traversal_path_is_refused(self):
        r = run("bundle.zip", zip_of({"../../etc/passwd": b"root:x:0:0:\n"}))
        assert r.status == VS.rejected.value
        assert r.reason == "unsafe_archive"

    def test_an_absolute_path_is_refused(self):
        r = run("bundle.zip", zip_of({"/etc/hosts": b"127.0.0.1 localhost\n"}))
        assert r.status == VS.rejected.value
        assert r.reason == "unsafe_archive"

    def test_a_symlink_entry_is_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            info = zipfile.ZipInfo("link")
            info.external_attr = (0o120777 << 16)  # S_IFLNK
            z.writestr(info, "/etc/passwd")
            z.writestr("guide.pdf", pdf())
        r = run("bundle.zip", buf.getvalue())
        assert r.status == VS.rejected.value
        assert r.reason == "unsafe_archive"

    def test_too_many_entries_is_refused(self):
        budget = ov.InspectionBudget(max_entries=5)
        data = zip_of({f"f{i}.txt": b"x" for i in range(6)})
        r = run("bundle.zip", data, budget=budget)
        assert r.status == VS.rejected.value
        assert r.reason == "too_many_entries"

    def test_a_high_ratio_entry_is_refused(self):
        """A classic bomb shape: one entry that expands enormously."""
        r = run("bundle.zip", zip_of({"big.txt": b"\x00" * (3 * 1024 * 1024)}))
        assert r.status == VS.rejected.value
        assert r.reason == "zip_bomb"

    def test_the_declared_total_ceiling_is_enforced(self):
        budget = ov.InspectionBudget(max_decompressed_bytes=1024)
        data = zip_of({"a.txt": b"abcdefgh" * 400})
        r = run("bundle.zip", data, budget=budget)
        assert r.status == VS.rejected.value
        assert r.reason in ("zip_bomb", "inspection_budget_exceeded")

    def test_an_unsupported_type_inside_is_refused(self):
        r = run("bundle.zip", zip_of({"photo.tiff": b"II*\x00" + b"\x00" * 64}))
        assert r.status == VS.rejected.value
        assert r.reason == "zip_contents"


# ---------------------------------------------------------------------------
# 4 · CSV — complete inspection, and negative numbers survive
# ---------------------------------------------------------------------------


class TestCsvFormulaProtection:
    @pytest.mark.parametrize("cell", [
        "-5", "-1.5", "+3", "+3.5", "-1.2e-4", "-0.0", "1200.50",
        "-99999999", ".5", "-.5",
    ])
    def test_legitimate_numbers_including_negatives_pass(self, cell):
        """The test that protects creators. A naive "reject cells
        starting with = + - @" rule rejects every one of these."""
        data = f"label,amount\nopening,{cell}\n".encode()
        r = run("budget.csv", data, "text/csv")
        assert r.status == VS.passed.value, (cell, r.reason)

    @pytest.mark.parametrize("cell", [
        "=1+1",
        "=cmd|'/c calc'!A0",
        "@SUM(A1:A2)",
        "-2+3+cmd|'/c calc'!A0",
        "+WEBSERVICE(\"http://x\")",
        "=HYPERLINK(\"http://x\")",
    ])
    def test_formula_cells_are_refused(self, cell):
        data = f"label,value\nrow,{cell}\n".encode()
        r = run("budget.csv", data, "text/csv")
        assert r.status == VS.rejected.value
        assert r.reason == "csv_formula"

    @pytest.mark.parametrize("prefix", [
        " ", "  ", "\t", "\r", "\x00", "\x0b", "\x0c", " ", "​", "﻿",
    ])
    def test_whitespace_and_control_characters_cannot_smuggle_a_formula(self, prefix):
        """Spreadsheet apps skip these before parsing, so a check on
        the literal first character is bypassable. Requested
        explicitly in the refinements."""
        data = ("label,value\nrow,\"" + prefix + "=cmd|'/c calc'!A0\"\n").encode()
        r = run("budget.csv", data, "text/csv")
        assert r.status == VS.rejected.value, prefix
        assert r.reason == "csv_formula"

    def test_a_payload_marker_anywhere_in_a_cell_is_refused(self):
        data = b'label,value\nrow,"harmless text DDE(cmd) more"\n'
        r = run("notes.csv", data, "text/csv")
        assert r.status == VS.rejected.value
        assert r.reason == "csv_formula"

    def test_text_that_merely_contains_an_equals_sign_passes(self):
        """The precision control: ``=`` mid-cell is not a formula."""
        data = b"label,value\nnote,\"width = 30cm\"\n"
        assert run("notes.csv", data, "text/csv").status == VS.passed.value

    def test_a_csv_too_large_to_check_is_rejected_not_passed(self):
        """Approved refinement: never approve on a partial inspection.
        A file beyond the budget is refused with a useful message."""
        budget = ov.InspectionBudget(max_csv_bytes=1024)
        data = b"a,b\n" + (b"1,2\n" * 2000)
        r = run("big.csv", data, "text/csv", budget=budget)
        assert r.status == VS.rejected.value
        assert r.reason == "csv_too_large_to_check"
        assert "split" in r.message.lower()

    def test_too_many_rows_is_rejected_not_passed(self):
        budget = ov.InspectionBudget(max_csv_rows=10)
        data = b"a,b\n" + (b"1,2\n" * 50)
        r = run("big.csv", data, "text/csv", budget=budget)
        assert r.status == VS.rejected.value
        assert r.reason == "csv_too_large_to_check"

    def test_a_passing_csv_records_that_inspection_was_complete(self):
        """So "we checked all of it" is in the record, not assumed."""
        r = run("budget.csv", b"a,b\n1,-2\n", "text/csv")
        entry = next(c for c in r.checks if c.id == "csv_formula")
        assert "'complete': True" in entry.detail

    def test_a_csv_inside_a_bundle_is_inspected_too(self):
        r = run("bundle.zip", zip_of({"data.csv": b"a,b\nx,=cmd|'/c calc'!A0\n"}))
        assert r.status == VS.rejected.value


# ---------------------------------------------------------------------------
# 5 · Budgets are enforced, not assumed
# ---------------------------------------------------------------------------


class TestBudgets:
    def test_the_time_budget_is_checked_inside_the_loops(self):
        budget = ov.InspectionBudget(max_seconds=-1.0)  # already expired
        with pytest.raises(ov.BudgetExceeded) as exc:
            budget.tick()
        assert exc.value.limit == "time"

    def test_an_exhausted_time_budget_rejects_rather_than_approves(self):
        """A file we cannot finish inspecting is never passed."""
        budget = ov.InspectionBudget(max_seconds=-1.0)
        r = run("bundle.zip", zip_of({"guide.pdf": pdf()}), budget=budget)
        assert r.status == VS.rejected.value
        assert r.reason == "inspection_budget_exceeded"

    def test_the_byte_budget_counts_actual_decompressed_bytes(self):
        budget = ov.InspectionBudget(max_decompressed_bytes=100)
        with pytest.raises(ov.BudgetExceeded) as exc:
            budget.spend_bytes(101)
        assert exc.value.limit == "decompressed_size"

    def test_memory_is_bounded_by_a_fixed_chunk(self):
        assert ov.CHUNK <= 256 * 1024
        assert ov.SNIFF <= 4096


# ---------------------------------------------------------------------------
# 6 · The record is honest
# ---------------------------------------------------------------------------


class TestValidationRecord:
    def test_no_field_or_value_claims_a_malware_scan(self):
        """The approved constraint: structural validation must never be
        represented as antivirus scanning."""
        cols = {c.name for c in OfferingFile.__table__.columns}
        for banned in ("scan_status", "scanned", "malware", "virus", "safe",
                       "clean", "security_status"):
            assert not any(banned in c for c in cols), banned
        for s in VS:
            assert s.value not in ("clean", "safe", "scanned")

    def test_no_antivirus_check_is_claimed_today(self):
        r = run("workbook.pdf", pdf())
        ids = {c.id for c in r.checks}
        assert "antivirus" not in ids
        assert not any("virus" in i or "malware" in i for i in ids)

    def test_the_record_names_the_policy_version(self):
        r = run("workbook.pdf", pdf())
        assert r.policy_version == ov.VALIDATION_POLICY_VERSION

    def test_a_not_applicable_check_is_recorded_rather_than_omitted(self):
        """An omitted entry would be indistinguishable from a check
        that never ran, which is the thing the record exists to
        prevent."""
        r = run("workbook.pdf", pdf())
        zc = next(c for c in r.checks if c.id == "zip_contents")
        assert zc.outcome == "pass"
        assert zc.detail == "not_applicable"

    def test_missing_required_detects_an_incomplete_record(self):
        assert ov.missing_required([]) == ov.required_check_ids()
        full = [{"id": c.id, "outcome": "pass"} for c in ov.REQUIRED_CHECKS]
        assert ov.missing_required(full) == frozenset()

    def test_a_failed_check_does_not_count_as_performed(self):
        recs = [{"id": c.id, "outcome": "pass"} for c in ov.REQUIRED_CHECKS]
        recs[0] = {"id": recs[0]["id"], "outcome": "fail"}
        assert recs[0]["id"] in ov.missing_required(recs)


# ---------------------------------------------------------------------------
# 7 · Download authorisation
# ---------------------------------------------------------------------------


def _offering(db, space, **kw) -> Offering:
    d = dict(id=_uid("off"), space_id=space.id, created_by_user_id=space.creator_id,
             slug=f"g-{uuid.uuid4().hex[:8]}", title="Guide",
             status=OfferingStatus.published.value)
    d.update(kw)
    row = Offering(**d); db.add(row); db.flush(); return row


def _file(db, off, *, name="workbook.pdf", status=VS.passed.value, **kw) -> OfferingFile:
    d = dict(id=_uid("ofl"), offering_id=off.id,
             storage_key=of.build_storage_key(offering_id=off.id, filename=name),
             original_filename=name, content_type="application/pdf",
             byte_size=2048, sort_order=0, validation_status=status,
             checks_performed=[{"id": c.id, "version": c.version, "outcome": "pass"}
                               for c in ov.REQUIRED_CHECKS],
             validation_policy_version=ov.VALIDATION_POLICY_VERSION)
    d.update(kw)
    row = OfferingFile(**d); db.add(row); db.flush(); return row


def _entitle(db, user, off, **kw) -> OfferingEntitlement:
    d = dict(id=_uid("oen"), user_id=user.id, offering_id=off.id,
             space_id=off.space_id,
             source=OfferingEntitlementSource.one_time_purchase.value,
             status=OfferingEntitlementStatus.active.value)
    d.update(kw)
    row = OfferingEntitlement(**d); db.add(row); db.flush(); return row


def _auth(key, user, db):
    try:
        authorize_upload(key, user, db)
        return None
    except HTTPException as e:
        return e.status_code


class TestDownloadGate:
    @pytest.mark.parametrize("st", ["pending", "rejected", "error", "quarantined"])
    def test_an_unvalidated_file_is_refused_an_entitled_purchaser(
        self, db, make_space, make_user, st,
    ):
        off = _offering(db, make_space())
        f = _file(db, off, status=st)
        buyer = make_user(); _entitle(db, buyer, off); db.flush()
        assert _auth(f.storage_key, buyer, db) == 403

    def test_a_passed_file_is_served_to_an_entitled_purchaser(
        self, db, make_space, make_user,
    ):
        """Positive control for the four refusals above."""
        off = _offering(db, make_space())
        f = _file(db, off)
        buyer = make_user(); _entitle(db, buyer, off); db.flush()
        assert _auth(f.storage_key, buyer, db) is None

    @pytest.mark.parametrize("st", ["pending", "rejected", "error", "quarantined"])
    def test_managers_cannot_download_unvalidated_files_either(
        self, db, make_space, make_user, st,
    ):
        """The bypass this closes: a manager could otherwise mint a
        pre-signed URL for an unchecked file and paste it anywhere,
        distributing unvalidated content as an approved download."""
        from app.models.user import User
        space = make_space()
        off = _offering(db, space)
        f = _file(db, off, status=st)
        db.flush()
        owner = db.query(User).filter(User.id == space.creator_id).one()
        assert _auth(f.storage_key, owner, db) == 403
        assert _auth(f.storage_key, make_user(role="admin"), db) == 403

    def test_a_manager_can_still_read_a_superseded_but_passed_file(
        self, db, make_space, make_user,
    ):
        """Phase A's recovery and audit access, preserved — validation
        narrowed *which* files, not manager access as such."""
        from app.models.user import User
        space = make_space()
        off = _offering(db, space)
        old = _file(db, off, name="v1.pdf", superseded_at=datetime.utcnow())
        db.flush()
        owner = db.query(User).filter(User.id == space.creator_id).one()
        assert _auth(old.storage_key, owner, db) is None

    def test_quarantining_withdraws_access_from_a_purchaser(
        self, db, make_space, make_user,
    ):
        off = _offering(db, make_space())
        f = _file(db, off)
        buyer = make_user(); _entitle(db, buyer, off); db.flush()
        assert _auth(f.storage_key, buyer, db) is None

        svc.quarantine_file(db, file=f, reason="credible_threat")
        db.flush()
        assert _auth(f.storage_key, buyer, db) == 403


class TestFeatureFlagSeparation:
    def test_an_owner_can_download_with_the_feature_disabled(
        self, db, make_space, make_user,
    ):
        """The approved separation. Turning Offerings off stops new
        activity; it must not take away a file somebody paid for."""
        from app.core.config import settings
        assert settings.offerings_enabled is False
        off = _offering(db, make_space())
        f = _file(db, off)
        buyer = make_user(); _entitle(db, buyer, off); db.flush()
        assert _auth(f.storage_key, buyer, db) is None

    def test_covers_are_still_gated_by_the_feature_flag(self, db, make_space):
        """Presentation follows availability; property does not."""
        from app.models.user import User
        off = _offering(db, make_space())
        db.flush()
        owner = db.query(User).filter(User.id == off.created_by_user_id).one()
        key = f"{of.OFFERING_COVERS_PREFIX}/{off.id}/{uuid.uuid4().hex}_c.png"
        assert _auth(key, owner, db) == 403

    def test_the_download_resolver_does_not_read_the_flag(self):
        """Source contract, so the separation cannot be undone by a
        well-meaning edit.

        The resolver's docstring explains the rule at length and names
        the flag while doing so, so a substring check over the raw
        source fails on the explanation rather than on a real read.
        The docstring is removed via the AST and the remaining
        statements are checked — banning the use, not the word.
        """
        import ast
        import inspect
        import textwrap
        from app.uploads import authorization

        src = textwrap.dedent(
            inspect.getsource(authorization._authorise_offering_file)
        )
        fn = ast.parse(src).body[0]
        body = fn.body[1:] if (
            isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)
            and isinstance(fn.body[0].value.value, str)
        ) else fn.body
        code = "\n".join(ast.dump(node) for node in body)
        assert "offerings_enabled" not in code, (
            "the download resolver must not read the feature flag — "
            "entitlement decides downloads"
        )
        # And the control: the covers resolver still does.
        covers = textwrap.dedent(
            inspect.getsource(authorization._authorise_offering_cover)
        )
        cfn = ast.parse(covers).body[0]
        cbody = cfn.body[1:] if (
            isinstance(cfn.body[0], ast.Expr)
            and isinstance(cfn.body[0].value, ast.Constant)
        ) else cfn.body
        assert "offerings_enabled" in "\n".join(
            ast.dump(n) for n in cbody
        ), "covers are presentation and should stay behind the flag"

    def test_every_offering_route_is_gated_by_the_feature_flag(self):
        """**Updated in B4.** This asserted that no Offering route
        existed at all, which was true while the phase shipped no
        endpoints. B4 adds the creator API, so the guarantee it was
        really protecting — nothing reachable while Offerings is off —
        moves from "no routes" to "every route gated".

        Rewritten rather than deleted, so the change of fact is visible
        in the suite's history.
        """
        from fastapi.routing import APIRoute
        from app.main import app
        routes = [
            r for r in app.routes
            if isinstance(r, APIRoute) and "offerings" in r.path
        ]
        assert routes, "B4 ships the creator API; expected routes"
        for r in routes:
            names = [
                getattr(d.call, "__name__", "") for d in r.dependant.dependencies
            ]
            assert "require_offerings_enabled" in names, r.path


# ---------------------------------------------------------------------------
# 8 · Replacement, revalidation and quarantine
# ---------------------------------------------------------------------------


class TestReplacementAndRevalidation:
    def test_the_approved_version_stays_available_while_a_replacement_validates(
        self, db, make_space, make_user,
    ):
        """Why validation is a separate axis from supersession: with one
        combined field there would be a window serving neither."""
        off = _offering(db, make_space())
        current = _file(db, off, name="v1.pdf")
        buyer = make_user(); _entitle(db, buyer, off); db.flush()
        assert _auth(current.storage_key, buyer, db) is None

        incoming = _file(db, off, name="v2.pdf", status=VS.pending.value)
        db.flush()
        assert _auth(current.storage_key, buyer, db) is None, "old still served"
        assert _auth(incoming.storage_key, buyer, db) == 403, "new not yet"

        incoming.validation_status = VS.passed.value
        current.superseded_at = datetime.utcnow()
        current.superseded_by_id = incoming.id
        db.flush()
        assert _auth(incoming.storage_key, buyer, db) is None
        assert _auth(current.storage_key, buyer, db) == 403

    def test_a_file_approved_under_an_older_policy_is_flagged_not_revoked(
        self, db, make_space, make_user,
    ):
        """Policy growth must not take access away — but it must be
        visible that the file has not had the newer check."""
        off = _offering(db, make_space())
        f = _file(db, off, checks_performed=[{"id": "declared", "version": 1,
                                              "outcome": "pass"}])
        buyer = make_user(); _entitle(db, buyer, off); db.flush()
        assert svc.needs_revalidation(f) is True
        assert _auth(f.storage_key, buyer, db) is None, "access retained"
        assert ov.missing_required(f.checks_performed), "gap is visible"

    def test_a_fully_recorded_file_needs_no_revalidation(self, db, make_space):
        off = _offering(db, make_space())
        assert svc.needs_revalidation(_file(db, off)) is False

    def test_a_passing_revalidation_upgrades_the_record_silently(
        self, db, make_space, make_user,
    ):
        off = _offering(db, make_space())
        f = _file(db, off, checks_performed=[{"id": "declared", "version": 1,
                                              "outcome": "pass"}])
        buyer = make_user(); _entitle(db, buyer, off); db.flush()
        report = run("workbook.pdf", pdf())
        assert svc.revalidate_file(db, file=f, report=report) == VS.passed.value
        db.flush()
        assert ov.missing_required(f.checks_performed) == frozenset()
        assert _auth(f.storage_key, buyer, db) is None

    def test_a_failing_revalidation_quarantines_despite_prior_approval(
        self, db, make_space, make_user,
    ):
        """The refinement spelled out: a credible problem found later
        must not be ignored because the file was approved before."""
        off = _offering(db, make_space())
        f = _file(db, off)
        buyer = make_user(); _entitle(db, buyer, off); db.flush()
        assert _auth(f.storage_key, buyer, db) is None

        bad = run("holiday.pdf", mp4(), "application/pdf")
        assert bad.status == VS.rejected.value
        assert svc.revalidate_file(db, file=f, report=bad) == VS.quarantined.value
        db.flush()
        assert f.quarantined_at is not None
        assert _auth(f.storage_key, buyer, db) == 403

    def test_quarantine_and_rejection_are_distinguishable(self, db, make_space):
        """Different events, so the history stays truthful."""
        off = _offering(db, make_space())
        rejected = _file(db, off, name="a.pdf", status=VS.rejected.value)
        approved = _file(db, off, name="b.pdf")
        db.flush()
        svc.quarantine_file(db, file=approved, reason="reported_by_member")
        db.flush()
        assert rejected.validation_status == "rejected"
        assert rejected.quarantined_at is None
        assert approved.validation_status == "quarantined"
        assert approved.quarantined_at is not None

    def test_a_quarantine_timestamp_requires_the_quarantined_status(
        self, db, make_space,
    ):
        off = _offering(db, make_space())
        f = _file(db, off)
        f.quarantined_at = datetime.utcnow()  # but status stays 'passed'
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_an_invalid_status_is_refused_by_the_database(self, db, make_space):
        off = _offering(db, make_space())
        with pytest.raises(IntegrityError):
            _file(db, off, status="clean")
            db.flush()
        db.rollback()


class TestInconclusiveHandling:
    def test_an_inconclusive_attempt_becomes_error_never_passed(
        self, db, make_space,
    ):
        off = _offering(db, make_space())
        f = _file(db, off, status=VS.pending.value)
        svc.record_inconclusive(db, file=f, detail="worker killed")
        db.flush()
        assert f.validation_status == VS.error.value
        assert f.validation_attempts == 1

    def test_retries_are_bounded(self, db, make_space):
        off = _offering(db, make_space())
        f = _file(db, off, status=VS.pending.value)
        for _ in range(svc.MAX_VALIDATION_ATTEMPTS):
            assert svc.should_retry(f) or f.validation_attempts == 0
            svc.record_inconclusive(db, file=f, detail="again")
        db.flush()
        assert svc.should_retry(f) is False

    def test_default_status_is_pending(self, db, make_space):
        """The safe state is the automatic one."""
        off = _offering(db, make_space())
        row = OfferingFile(
            id=_uid("ofl"), offering_id=off.id,
            storage_key=of.build_storage_key(offering_id=off.id, filename="x.pdf"),
            original_filename="x.pdf", content_type="application/pdf",
            byte_size=10, sort_order=0,
        )
        db.add(row); db.flush(); db.refresh(row)
        assert row.validation_status == VS.pending.value
        assert row.checks_performed == []
        assert row.is_downloadable is False


# ---------------------------------------------------------------------------
# 9 · Nothing else moved
# ---------------------------------------------------------------------------


class TestExistingBehaviourUnchanged:
    def test_the_pre_existing_upload_namespaces_still_dispatch(self):
        from app.uploads import authorization
        for p in ("avatars", "covers", "logos", "island-artwork",
                  "pathway-covers", "event-thumbnails", "steps", "media"):
            assert p in authorization._DISPATCH, p

    def test_the_global_upload_allow_list_is_still_narrow(self):
        from app.core.storage import ALLOWED_EXTENSIONS
        for ext in (".zip", ".xlsx", ".csv", ".pptx", ".xls", ".ppt"):
            assert ext not in ALLOWED_EXTENSIONS, ext

    def test_gathering_capacity_rule_is_unchanged(self):
        from app.services.gathering_tickets import CAPACITY_USED_SQL
        sql = str(CAPACITY_USED_SQL)
        assert "pending_payment" in sql and "confirmed" in sql
        assert "hold_expires_at" not in sql

    def test_the_original_grant_kinds_keep_their_values(self):
        """Migration 162 widened the kinds with ``offering``. The three
        that existed before carry live production rows, so their values
        must not move."""
        from app.models import payment_option_grant as pog
        assert (pog.GRANT_KIND_PATHWAY, pog.GRANT_KIND_EVENT_SERIES,
                pog.GRANT_KIND_GATHERING) == ("pathway", "event_series", "gathering")
        assert pog.GRANT_KIND_OFFERING == "offering"

    def test_the_offer_pages_table_and_migration_survive(self):
        from app.db.base import Base
        assert "offer_pages" in Base.metadata.tables
        versions = pathlib.Path(__file__).parent.parent / "alembic" / "versions"
        assert (versions / "104_offer_pages.py").exists()

    def test_no_existing_table_gained_a_validation_column(self):
        from app.db.base import Base
        allowed = {"offering_files"}
        for name, table in Base.metadata.tables.items():
            if name in allowed:
                continue
            bad = [c.name for c in table.columns
                   if "validation" in c.name or "checks_performed" in c.name]
            assert bad == [], f"{name}: {bad}"
