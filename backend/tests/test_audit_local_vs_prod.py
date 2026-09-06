"""Tests for the local-vs-prod audit script.

Covers:
  * Pure helpers (_same_db, _sanitised_url, _normalise_jsonish, _shorten)
  * Diff shape via a real local test-DB session used for BOTH sides
    (proves the diff engine returns 'all identical' when the same DB
    is compared to itself — impossible to run for real due to the
    _same_db safeguard, but exercisable at the helper level).
  * Table-auditor logic with two divergent in-memory-ish datasets.
  * Mother World completeness classification with fixture Locations.
  * FK reachability with a Space whose location_id references a
    Location whose key is absent in a stand-in "prod" session.
  * Structural safety: the audit source file must contain no
    INSERT/UPDATE/DELETE/DDL verbs.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
import audit_local_vs_prod as audit  # noqa: E402

from app.models.place import Place, SpacePlace  # noqa: E402
from app.models.platform import (  # noqa: E402
    AtmosphereOption,
    ColourStory,
    ElementOption,
    LandscapeOption,
    Location,
    PathwayType,
    Space,
    SpaceStatus,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestSameDb:
    def test_identical(self):
        assert audit._same_db("postgresql://a@h/db", "postgresql://a@h/db")

    def test_different_creds_same_host_still_match(self):
        assert audit._same_db(
            "postgresql://u1:p1@h/db",
            "postgresql://u2:p2@h/db",
        )

    def test_different_dbs(self):
        assert not audit._same_db(
            "postgresql://a@h/db_local",
            "postgresql://a@h/db_prod",
        )


class TestSanitisedUrl:
    def test_password_stripped(self):
        s = audit._sanitised_url("postgresql://u:supersecret@host:5432/db")
        assert "supersecret" not in s
        assert "u" in s and "host" in s and "db" in s


class TestNormaliseJsonish:
    def test_list_sorted(self):
        # Element order in JSON lists should not produce false diffs.
        assert audit._normalise_jsonish(["b", "a"]) == audit._normalise_jsonish(["a", "b"])

    def test_scalar_passthrough(self):
        assert audit._normalise_jsonish("x") == "x"
        assert audit._normalise_jsonish(None) is None


class TestShorten:
    def test_short_string_untouched(self):
        assert audit._shorten("abc") == "abc"

    def test_long_string_truncated(self):
        v = "x" * 200
        out = audit._shorten(v, limit=50)
        assert out.endswith("...")
        assert len(out) == 53

    def test_none_untouched(self):
        assert audit._shorten(None) is None


# ---------------------------------------------------------------------------
# Structural safety — no writes in the script
# ---------------------------------------------------------------------------


class TestEveryAuditorImportsAndRuns:
    """Regression guard for import-drift bugs like the CommunicationTopic
    ImportError from the first prod run.

    Constructs an empty test-DB session as both local and prod, then
    invokes every registered auditor. If any auditor holds a stale
    import path (e.g. class moved between modules) or has a missing
    top-level import, this test surfaces the error immediately instead
    of during a real audit run against production."""

    def test_all_15_auditors_execute_against_the_test_db(self, db: Session):
        # We're using the same session for both sides. What we care
        # about here is that (a) every model reference resolves via
        # import — no ImportError like the one that killed the first
        # prod run — (b) every auditor's query chain constructs and
        # returns without exception, (c) the returned TableAudit has
        # the right shape, and (d) when the same session is used on
        # both sides, every row is IDENTICAL (no LOCAL_ONLY /
        # PROD_ONLY / DIFFERENT). Test DB row counts vary by
        # migration seed content and are not asserted directly.
        assert len(audit._AUDITORS) == 15, (
            "expected 15 registered auditors — update this assertion "
            "if the audit scope changes"
        )
        for label, auditor_fn in audit._AUDITORS:
            result = auditor_fn(db, db)
            assert isinstance(result, audit.TableAudit), (
                f"{label}: auditor must return TableAudit, "
                f"got {type(result).__name__}"
            )
            # Same-session-both-sides invariants — row counts match
            # and no drift is reported.
            assert result.total_local == result.total_prod, (
                f"{label}: same-session totals must match "
                f"({result.total_local} vs {result.total_prod})"
            )
            assert result.identical == result.total_local, (
                f"{label}: same-session should be all IDENTICAL"
            )
            assert result.different == [], f"{label}: no DIFFERENT rows"
            assert result.local_only == [], f"{label}: no LOCAL_ONLY rows"
            assert result.prod_only == [], f"{label}: no PROD_ONLY rows"

    def test_mother_world_and_fk_auditors_also_construct(self, db: Session):
        # Same guard for the non-per-table auditors.
        mw = audit.audit_mother_world(db, db)
        assert isinstance(mw, audit.MotherWorldReport)
        issues = audit.audit_fk_reachability(db, db)
        assert isinstance(issues, list)


class TestSourceHasNoWrites:
    def test_source_contains_no_write_verbs(self):
        source_path = _SCRIPTS / "audit_local_vs_prod.py"
        # Strip docstring + comments so example text in doc doesn't
        # trip the check (there is no such text at time of writing,
        # but a future edit shouldn't be able to add any).
        raw = source_path.read_text()
        stripped = "\n".join(
            line for line in raw.split("\n")
            if not line.lstrip().startswith("#")
        )
        # Strip triple-quoted docstrings too.
        import re
        stripped = re.sub(r'"""[\s\S]*?"""', "", stripped)
        stripped = re.sub(r"'''[\s\S]*?'''", "", stripped)

        # SQL keywords — case-sensitive uppercase match. Python
        # snake_case names like ``sys.path.insert(...)`` or a var
        # called ``update_at`` are legitimate and must not trip the
        # check; SQL DML is conventionally written UPPERCASE in
        # string literals when it appears.
        sql_verbs = (
            r"\bINSERT\s+INTO\b", r"\bUPDATE\s+\w+\s+SET\b",
            r"\bDELETE\s+FROM\b", r"\bDROP\s+(TABLE|INDEX|COLUMN)\b",
            r"\bALTER\s+TABLE\b", r"\bTRUNCATE\s+TABLE\b",
            r"\bCREATE\s+TABLE\b",
        )
        for pat in sql_verbs:
            assert not re.search(pat, stripped), (
                f"audit script must not contain SQL DML {pat!r} — read-only"
            )

        # ORM mutation methods — the SQLAlchemy Session API names
        # for adding, deleting, committing, merging. Case-sensitive
        # since Python names are case-sensitive.
        for method in (".add(", ".delete(", ".commit(", ".merge(",
                       ".add_all(", ".flush(", ".execute(text("):
            # Allow ``dict.update()``, ``list.append()``, ``str.split()``
            # by anchoring to session-shaped names. Match ``session.``
            # or ``prod.`` or ``local.`` or ``db.`` prefixes.
            for prefix in ("session", "prod", "local", "db"):
                needle = prefix + method
                assert needle not in stripped, (
                    f"audit script must not call {needle!r} — read-only"
                )


# ---------------------------------------------------------------------------
# Table-auditor logic via a real (test-DB) session used as both sides
# ---------------------------------------------------------------------------
#
# The _same_db safeguard prevents running the script against a single
# DB in production. But at the helper level ``_audit_by_natural_key``
# is a pure function of two Sessions — we can feed it the same session
# twice OR two different SAVEPOINT views of the same test DB to
# exercise the diff branches.


@pytest.fixture
def sample_atmospheres(db: Session):
    """Insert three atmospheres into the local test DB. Also stash
    them in an in-memory dict simulating a slightly different 'prod'
    state that we'll drive via a MagicMock session in tests below."""
    for row in [
        AtmosphereOption(id=_uid("atm"), key="playful", name="Playful",
                         position=0, is_active=True),
        AtmosphereOption(id=_uid("atm"), key="grounded", name="Grounded",
                         position=1, is_active=True),
        AtmosphereOption(id=_uid("atm"), key="brave", name="Brave",
                         position=2, is_active=True),
    ]:
        db.add(row)
    db.commit()


class TestAuditByNaturalKey:
    def test_same_session_both_sides_reports_all_identical(
        self, db: Session, sample_atmospheres,
    ):
        # Using the same session as both sides — every row matches.
        result = audit._audit_by_natural_key(
            label="AtmosphereOption",
            tablename="atmosphere_options",
            model=AtmosphereOption,
            natural_key="key",
            local=db, prod=db,
            identity_fields=["name", "position", "is_active"],
        )
        assert result.total_local == result.total_prod == 3
        assert result.identical == 3
        assert result.different == []
        assert result.local_only == []
        assert result.prod_only == []

    def test_stand_in_prod_missing_a_row_reports_local_only(
        self, db: Session, sample_atmospheres,
    ):
        # Build a synthetic "prod" session that returns only two of the
        # three rows. We use a MagicMock for the .query().all() chain.
        local_rows = db.query(AtmosphereOption).all()
        keep = [r for r in local_rows if r.key != "brave"]

        prod_session = MagicMock()
        prod_session.query.return_value.all.return_value = keep

        result = audit._audit_by_natural_key(
            label="AtmosphereOption",
            tablename="atmosphere_options",
            model=AtmosphereOption,
            natural_key="key",
            local=db, prod=prod_session,
            identity_fields=["name", "position", "is_active"],
        )
        assert result.total_local == 3
        assert result.total_prod == 2
        assert result.identical == 2
        assert len(result.local_only) == 1
        assert result.local_only[0]["key"] == "brave"

    def test_stand_in_prod_extra_row_reports_prod_only(
        self, db: Session, sample_atmospheres,
    ):
        local_rows = db.query(AtmosphereOption).all()
        extra = AtmosphereOption(
            id="atm_prod_extra", key="prod-only", name="Prod Extra",
            position=99, is_active=True,
        )
        prod_session = MagicMock()
        prod_session.query.return_value.all.return_value = local_rows + [extra]

        result = audit._audit_by_natural_key(
            label="AtmosphereOption",
            tablename="atmosphere_options",
            model=AtmosphereOption,
            natural_key="key",
            local=db, prod=prod_session,
            identity_fields=["name", "position", "is_active"],
        )
        assert result.total_local == 3
        assert result.total_prod == 4
        assert result.identical == 3
        assert len(result.prod_only) == 1
        assert result.prod_only[0]["key"] == "prod-only"

    def test_field_drift_reports_different_with_diff_fields(
        self, db: Session, sample_atmospheres,
    ):
        # Prod's 'playful' has a different name AND is_active flag.
        # Should surface as DIFFERENT with both field diffs.
        local_rows = db.query(AtmosphereOption).all()
        prod_rows = [
            AtmosphereOption(
                id=r.id, key=r.key,
                name=("Playful (edited)" if r.key == "playful" else r.name),
                position=r.position,
                is_active=(False if r.key == "playful" else r.is_active),
            )
            for r in local_rows
        ]
        prod_session = MagicMock()
        prod_session.query.return_value.all.return_value = prod_rows

        result = audit._audit_by_natural_key(
            label="AtmosphereOption",
            tablename="atmosphere_options",
            model=AtmosphereOption,
            natural_key="key",
            local=db, prod=prod_session,
            identity_fields=["name"],
            compare_fields=["name", "position", "is_active"],
        )
        assert result.identical == 2
        assert len(result.different) == 1
        row = result.different[0]
        assert row.key == "playful"
        diff_fields = {f.field for f in row.fields}
        assert diff_fields == {"name", "is_active"}


class TestMediaUrlDiffsSurfaceSeparately:
    def test_url_only_diff_goes_to_media_bucket_not_different(
        self, db: Session,
    ):
        # Two locations, one whose hero_artwork_url differs between
        # environments but every other field matches. Should show up
        # in media_url_differs, NOT in different.
        loc_a = Location(
            id=_uid("loc"), key="sanctuary-springs",
            name="Sanctuary Springs", status="active",
            location_type="ATLAS",
            hero_artwork_url="/api/uploads/atlas-locations/sanctuary-springs/local.png",
            position=1,
        )
        db.add(loc_a)
        db.commit()

        prod_row = Location(
            id="prod-id", key="sanctuary-springs",
            name="Sanctuary Springs", status="active",
            location_type="ATLAS",
            hero_artwork_url="/api/uploads/atlas-locations/sanctuary-springs/prod.png",
            position=1,
        )
        prod_session = MagicMock()
        prod_session.query.return_value.all.return_value = [prod_row]

        result = audit._audit_by_natural_key(
            label="Location", tablename="locations",
            model=Location, natural_key="key",
            local=db, prod=prod_session,
            identity_fields=["name", "status"],
            compare_fields=["name", "status", "hero_artwork_url"],
        )
        assert len(result.different) == 0
        assert len(result.media_url_differs) == 1
        assert result.media_url_differs[0]["key"] == "sanctuary-springs"


class TestJsonListOrderDoesNotProduceFalseDiff:
    def test_preferred_atmospheres_order_irrelevant(
        self, db: Session,
    ):
        loc = Location(
            id=_uid("loc"), key="k", name="n", status="active",
            location_type="ATLAS", position=1,
            preferred_atmospheres=["a", "b", "c"],
        )
        db.add(loc)
        db.commit()
        prod_row = Location(
            id="p", key="k", name="n", status="active",
            location_type="ATLAS", position=1,
            preferred_atmospheres=["c", "a", "b"],  # different order
        )
        prod_session = MagicMock()
        prod_session.query.return_value.all.return_value = [prod_row]

        result = audit._audit_by_natural_key(
            label="Location", tablename="locations",
            model=Location, natural_key="key",
            local=db, prod=prod_session,
            identity_fields=["name"],
            compare_fields=["preferred_atmospheres"],
        )
        assert result.identical == 1
        assert len(result.different) == 0


# ---------------------------------------------------------------------------
# Mother World completeness
# ---------------------------------------------------------------------------


class TestMotherWorld:
    def test_classifies_by_location_type_and_reports_missing(
        self, db: Session,
    ):
        # Local: 2 cornerstones, 3 atlas, 1 community
        for kind, keys in (
            ("CORNERSTONE", ["cs-a", "cs-b"]),
            ("ATLAS", ["a1", "a2", "a3"]),
            ("COMMUNITY", ["c1"]),
        ):
            for k in keys:
                db.add(Location(
                    id=_uid("loc"), key=k, name=k.upper(),
                    status="active", location_type=kind, position=0,
                ))
        db.commit()

        # Stand-in prod session has fewer rows
        prod_rows = [
            Location(id="p1", key="cs-a", name="CS-A", status="active",
                     location_type="CORNERSTONE", position=0),
            Location(id="p2", key="a1", name="A1", status="active",
                     location_type="ATLAS", position=0),
        ]
        prod = MagicMock()
        # audit_mother_world uses ``session.query(Location).filter(...).all()``
        prod.query.return_value.filter.return_value.all.side_effect = [
            [r for r in prod_rows if r.location_type == "CORNERSTONE"],
            [r for r in prod_rows if r.location_type == "ATLAS"],
            [r for r in prod_rows if r.location_type == "COMMUNITY"],
        ]
        prod.query.return_value.all.return_value = []  # for Place

        report = audit.audit_mother_world(db, prod)
        assert report.cornerstones_local == 2
        assert report.cornerstones_prod == 1
        assert report.cornerstones_missing_from_prod == ["cs-b"]
        assert report.atlas_local == 3
        assert report.atlas_prod == 1
        assert set(report.atlas_missing_from_prod) == {"a2", "a3"}
        assert report.community_local == 1
        assert report.community_missing_from_prod == ["c1"]
        # Sanity notes flag deviations from the operator's expected
        # counts (3/19/3).
        assert any("Cornerstones" in n for n in report.sanity_notes)


# ---------------------------------------------------------------------------
# FK reachability
# ---------------------------------------------------------------------------


class TestFkReachability:
    @staticmethod
    def _prod_stub(rows_by_model: dict[type, list]) -> MagicMock:
        """Build a MagicMock 'prod' session whose ``.query(X).all()``
        returns the rows for X. Filter chains resolve to the same
        rows. Anything unspecified returns []."""
        prod = MagicMock()

        def _query_side_effect(model):
            q = MagicMock()
            rows = rows_by_model.get(model, [])
            q.all.return_value = rows
            q.filter.return_value = q
            return q

        prod.query.side_effect = _query_side_effect
        return prod

    def test_location_key_missing_in_prod_produces_issue(
        self, db: Session, make_user, make_space,
    ):
        creator = make_user(role="creator")
        loc = Location(
            id=_uid("loc"), key="sanctuary-springs",
            name="Sanctuary Springs", status="active",
            location_type="ATLAS", position=0,
        )
        db.add(loc)
        db.flush()
        space = make_space(creator=creator, status="draft")
        space.location_id = loc.id
        db.commit()

        # Prod has zero rows for every reference table.
        prod = self._prod_stub({})

        issues = audit.audit_fk_reachability(db, prod)
        location_issues = [
            i for i in issues
            if i.field == "location_id" and i.space_slug == space.slug
        ]
        assert len(location_issues) == 1
        assert location_issues[0].local_target_key == "sanctuary-springs"
        assert "not present in prod" in location_issues[0].reason

    def test_location_key_present_in_prod_no_issue(
        self, db: Session, make_user, make_space,
    ):
        creator = make_user(role="creator")
        loc = Location(
            id=_uid("loc"), key="sanctuary-springs",
            name="Sanctuary Springs", status="active",
            location_type="ATLAS", position=0,
        )
        db.add(loc)
        db.flush()
        space = make_space(creator=creator, status="draft")
        space.location_id = loc.id
        db.commit()

        # Prod has the same key (different UUID — that's the whole point)
        prod_loc = Location(
            id="prod-uuid", key="sanctuary-springs",
            name="Sanctuary Springs", status="active",
            location_type="ATLAS", position=0,
        )
        prod = self._prod_stub({Location: [prod_loc]})

        issues = audit.audit_fk_reachability(db, prod)
        location_issues = [
            i for i in issues
            if i.field == "location_id" and i.space_slug == space.slug
        ]
        assert len(location_issues) == 0
