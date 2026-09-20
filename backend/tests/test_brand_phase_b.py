"""Phase B — the brand actually reaching the product.

Phase A built the roles, the defaults and the resolver. This is the
phase where the teal rounded square that stood in for Fresh Collective
in ten places stops being rendered anywhere, and the tests here are
mostly about keeping it gone.

Two kinds of test live in this file.

Source tests read the repository. They are unusual and deliberate: the
placeholder was not a bug in one component, it was the same fourteen
lines copied into fourteen files, and the only way to stop that
happening again is to assert on the source rather than on one
rendering of it. A source test also catches the case a render test
cannot — a new component that draws its own mark and is not yet
mounted anywhere.

Behaviour tests cover the email header, which is the surface where
getting it wrong is most expensive and least visible: an email is sent
once, cannot be corrected, and a broken image in it is a broken image
in a permanent record of what Fresh Collective looks like.
"""

from __future__ import annotations

import io
import pathlib
import re
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.auth.dependencies import get_admin_user
from app.brand import BRAND_ASSET_ROLES, ROLE_ORDER, storage_key_for
from app.brand.email import (
    EMAIL_HEADER_ROLE,
    EMAIL_LOGO_PX,
    brand_header_html,
    email_logo_url,
)
from app.brand.resolver import bundled_default_public_url
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.platform import PlatformArtwork


REPO = pathlib.Path(__file__).resolve().parent.parent.parent
FRONTEND_SRC = REPO / "frontend" / "src"
BACKEND_APP = REPO / "backend" / "app"

# The component that owns brand rendering. It is the only place in the
# frontend allowed to name an asset path.
BRAND_MODULE = "@/components/brand/FreshCollectiveBrand"


def _tsx_sources() -> list[pathlib.Path]:
    return sorted(
        p for p in FRONTEND_SRC.rglob("*.tsx")
        if "node_modules" not in p.parts
    )


# ===========================================================================
# 1. The placeholder is gone and cannot come back
# ===========================================================================


# The exact shapes the old mark took across the codebase. It was always
# a small rounded box holding a smaller white chip; these are the chips.
PLACEHOLDER_FINGERPRINTS = (
    "h-3 w-3 rounded-sm bg-white",
    "h-[10px] w-[10px] rounded-sm bg-white",
    "rounded-sm bg-white/95",
    "rounded-[3px] bg-[color:var(--fc-ink-inverse)]",
)

# The email renderers drew the same thing in table markup.
EMAIL_PLACEHOLDER_FINGERPRINTS = (
    "width:12px;height:12px;background:#FFFFFF",
    "height:32px;border-radius:8px",
)


class TestPlaceholderIsGone:
    @pytest.mark.parametrize("fingerprint", PLACEHOLDER_FINGERPRINTS)
    def test_no_frontend_source_draws_the_teal_square(self, fingerprint):
        offenders = [
            str(p.relative_to(REPO))
            for p in _tsx_sources()
            if fingerprint in p.read_text()
        ]
        assert offenders == [], (
            f"the placeholder mark ({fingerprint!r}) is back in: {offenders}"
        )

    @pytest.mark.parametrize("fingerprint", EMAIL_PLACEHOLDER_FINGERPRINTS)
    def test_no_email_renderer_draws_the_teal_square(self, fingerprint):
        offenders = [
            str(p.relative_to(REPO))
            for p in sorted(BACKEND_APP.rglob("*.py"))
            if fingerprint in p.read_text()
        ]
        assert offenders == [], (
            f"the placeholder mark ({fingerprint!r}) is back in: {offenders}"
        )

    def test_only_the_brand_module_names_an_asset_path(self):
        """No component may reach for a file again. The three auth
        surfaces each had their own copy of the same path, which is how
        a logo change became a three-file change."""
        offenders = []
        for p in _tsx_sources():
            if "/brand/fresh-collective" in p.read_text():
                offenders.append(str(p.relative_to(REPO)))
        assert offenders == [], (
            f"raw brand asset paths outside the shared module: {offenders}"
        )

    def test_the_resolver_is_the_only_source_of_asset_paths(self):
        """``lib/brand.ts`` holds the default table; nothing else in
        the frontend may."""
        owners = [
            str(p.relative_to(FRONTEND_SRC))
            for p in sorted(FRONTEND_SRC.rglob("*.ts"))
            if "/brand/fresh-collective" in p.read_text()
        ]
        assert owners == ["lib/brand.ts"], owners


# ===========================================================================
# 2. Every audited surface now uses the shared components
# ===========================================================================


# The surfaces the audit found, and what each should render now.
MIGRATED_SURFACES = {
    "components/layout/PublicHeader.tsx": "BrandLockup",
    "components/layout/PublicFooter.tsx": "BrandLockup",
    "components/layout/WorldHeader.tsx": "BrandLockup",
    "app/creator-studio/CreatorStudioSidebar.tsx": "BrandLockup",
    "components/admin/AdminShell.tsx": "BrandLockup",
    "app/admin/login/AdminLoginForm.tsx": "BrandLockup",
    "components/platform/AppShell.tsx": "BrandLockup",
    "components/layout/AuthCard.tsx": "FreshCollectiveLogo",
    "app/signup/SignupForm.tsx": "FreshCollectiveLogo",
    "components/checkout/PrototypeSignupForm.tsx": "FreshCollectiveLogo",
}


class TestSurfacesUseSharedBranding:
    @pytest.mark.parametrize(
        "relative,component", sorted(MIGRATED_SURFACES.items()),
    )
    def test_surface_imports_and_uses_the_shared_component(
        self, relative, component,
    ):
        source = (FRONTEND_SRC / relative).read_text()
        assert BRAND_MODULE in source, f"{relative} does not import the brand module"
        assert f"<{component}" in source, (
            f"{relative} imports the brand module but does not render "
            f"{component}"
        )

    def test_the_audit_covered_every_surface_that_had_one(self):
        """Nothing was quietly left behind: any file rendering a brand
        component is either in the table above or is the module itself."""
        rendering = {
            str(p.relative_to(FRONTEND_SRC))
            for p in _tsx_sources()
            if BRAND_MODULE in p.read_text()
        }
        allowed = set(MIGRATED_SURFACES) | {
            "components/brand/FreshCollectiveBrand.tsx",
        }
        assert rendering <= allowed, rendering - allowed


# ===========================================================================
# 3. Auth pages show the brand once
# ===========================================================================


class TestAuthPagesDoNotDoubleBrand:
    def test_the_auth_shell_suppresses_the_header_brand(self):
        shell = (FRONTEND_SRC / "components/layout/AuthPageShell.tsx").read_text()
        assert "brand={false}" in shell, (
            "the auth shell must tell PublicHeader to drop its brand — "
            "the card below already carries the full logo"
        )

    def test_the_header_honours_the_suppression(self):
        header = (FRONTEND_SRC / "components/layout/PublicHeader.tsx").read_text()
        assert "brand = true" in header
        # Both variants, overlay and solid, must be guarded.
        assert header.count("{brand") >= 2

    def test_the_auth_card_logo_is_the_way_home(self):
        """Dropping the header brand also drops the link home, so the
        card's logo takes it over. Without that the auth pages have no
        route back to the public site."""
        for relative in (
            "components/layout/AuthCard.tsx",
            "app/signup/SignupForm.tsx",
            "components/checkout/PrototypeSignupForm.tsx",
        ):
            source = (FRONTEND_SRC / relative).read_text()
            assert 'href="/"' in source, relative

    def test_the_auth_card_uses_the_light_role(self):
        for relative in (
            "components/layout/AuthCard.tsx",
            "app/signup/SignupForm.tsx",
            "components/checkout/PrototypeSignupForm.tsx",
        ):
            source = (FRONTEND_SRC / relative).read_text()
            assert 'role="primary_light_logo"' in source, relative

    def test_the_full_logo_is_rendered_large_enough_to_read(self):
        """The old treatment was 44px, which prints the wordmark at
        1.3px. The component's own sizes are what fix that."""
        component = (
            FRONTEND_SRC / "components/brand/FreshCollectiveBrand.tsx"
        ).read_text()
        sizes = [int(m) for m in re.findall(r"h-\[(\d+)px\]", component)]
        assert sizes, "no explicit rendered height found"
        assert min(sizes) >= 200, sizes
        # 15/500 of the box is the wordmark cap height.
        assert max(sizes) * (15 / 500) >= 7.0, (
            "the largest rendered size still leaves the wordmark under "
            "7px and therefore unreadable"
        )


# ===========================================================================
# 4. Missing compact marks degrade to text, never to a fake icon
# ===========================================================================


class TestCompactMarksAreMissingHonestly:
    def test_the_compact_roles_are_still_missing(self):
        for role in ("compact_light_mark", "compact_dark_mark"):
            assert BRAND_ASSET_ROLES[role].default_path is None

    def test_the_frontend_agrees_they_are_missing(self):
        source = (FRONTEND_SRC / "lib/brand.ts").read_text()
        for role in ("compact_light_mark", "compact_dark_mark",
                     "favicon_app_icon", "social_share_image"):
            assert re.search(rf"{role}:\s*null", source), role

    def test_the_lockup_renders_no_image_when_the_mark_is_missing(self):
        """The whole point: with no compact artwork the lockup is live
        text. It must not substitute a full lockup, a cropped one, or
        anything resembling the old square."""
        component = (
            FRONTEND_SRC / "components/brand/FreshCollectiveBrand.tsx"
        ).read_text()
        # The <img> is guarded on the resolved URL existing.
        assert "{markUrl && (" in component
        assert "rounded-sm" not in component
        assert "linear-gradient" not in component

    def test_uploading_a_compact_mark_needs_no_further_code_change(self):
        """The lockup resolves the role at render time, so artwork
        uploaded in World Management appears everywhere at once."""
        component = (
            FRONTEND_SRC / "components/brand/FreshCollectiveBrand.tsx"
        ).read_text()
        assert "compactRoleFor(tone)" in component
        assert "useBrandOverrides()" in component


# ===========================================================================
# 5. The frontend default table matches the backend
# ===========================================================================


class TestFrontendContract:
    def test_bundled_defaults_agree_across_the_stack(self):
        """Two copies of the same table, one in Python and one in
        TypeScript, held in agreement here. Drift would mean a role
        resolving to different artwork depending on whether the answer
        came from an email or a page."""
        source = (FRONTEND_SRC / "lib/brand.ts").read_text()
        # Anchor on the declaration: the identifier also appears in
        # the module docstring and again where it is read.
        declaration = "export const BUNDLED_DEFAULTS"
        assert declaration in source
        block = source.split(declaration)[1].split("}")[0]
        parsed: dict[str, str | None] = {}
        for role in ROLE_ORDER:
            match = re.search(rf"{role}:\s*(null|'([^']+)')", block)
            assert match, f"{role} missing from the frontend table"
            parsed[role] = match.group(2) if match.group(2) else None

        expected = {r: BRAND_ASSET_ROLES[r].default_path for r in ROLE_ORDER}
        assert parsed == expected

    def test_every_frontend_default_exists_on_disk(self):
        source = (FRONTEND_SRC / "lib/brand.ts").read_text()
        for path in re.findall(r"'(/brand/[^']+)'", source):
            assert (REPO / "frontend" / "public" / path.lstrip("/")).is_file(), path


# ===========================================================================
# 6. The email header
# ===========================================================================


def _png(size: int = 512) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (size, size), (12, 24, 38, 255)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def admin(make_user):
    return make_user(role="admin", email_verified_at=datetime.utcnow())


@pytest.fixture
def client(db, admin):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_admin_user] = lambda: admin
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestEmailHeader:
    def test_it_carries_the_approved_logo_by_default(self, db):
        html = brand_header_html(db)
        assert bundled_default_public_url(EMAIL_HEADER_ROLE) in html

    def test_the_url_is_absolute_and_public(self, db):
        url = email_logo_url(db)
        assert url.startswith("https://") or url.startswith("http://")
        assert url.startswith(settings.resolved_public_app_url)

    def test_the_img_satisfies_every_email_client_rule(self, db):
        html = brand_header_html(db)
        assert 'alt="Fresh Collective"' in html
        assert 'border="0"' in html
        assert f'width="{EMAIL_LOGO_PX}"' in html
        assert f'height="{EMAIL_LOGO_PX}"' in html
        assert "display:block" in html
        # The three treatments that break in real clients.
        assert ".svg" not in html
        assert "data:" not in html
        assert "background-image" not in html

    def test_the_rendered_size_makes_the_wordmark_readable(self):
        assert EMAIL_LOGO_PX * (15 / 500) >= 7.0

    def test_an_admin_upload_reaches_the_email(self, db, client):
        client.post(
            f"/api/admin/brand-assets/{EMAIL_HEADER_ROLE}",
            files={"file": ("logo.png", _png(), "image/png")},
        )
        url = email_logo_url(db)
        assert "/platform-artwork/brand/" in url
        assert url != bundled_default_public_url(EMAIL_HEADER_ROLE)
        assert url in brand_header_html(db)

    def test_reset_returns_the_email_to_the_bundled_default(self, db, client):
        client.post(
            f"/api/admin/brand-assets/{EMAIL_HEADER_ROLE}",
            files={"file": ("logo.png", _png(), "image/png")},
        )
        assert email_logo_url(db) != bundled_default_public_url(EMAIL_HEADER_ROLE)

        client.delete(f"/api/admin/brand-assets/{EMAIL_HEADER_ROLE}")
        assert email_logo_url(db) == bundled_default_public_url(EMAIL_HEADER_ROLE)

    def test_a_private_url_can_never_reach_an_email(self, db):
        """A session-gated URL in an inbox is a broken image for every
        recipient. The resolver withholds it and the header falls back
        to artwork that actually loads."""
        db.add(PlatformArtwork(
            key=storage_key_for(EMAIL_HEADER_ROLE),
            image_url="/api/uploads/space-logos/private.png",
        ))
        db.flush()
        url = email_logo_url(db)
        assert "space-logos" not in url
        assert url == bundled_default_public_url(EMAIL_HEADER_ROLE)
        assert "space-logos" not in brand_header_html(db)

    def test_a_database_failure_still_sends_the_email(self):
        """The rule the editable-copy resolver already follows: a
        database problem must not stop an email going out."""
        class Broken:
            def query(self, *a, **k):
                raise RuntimeError("db down")

        url = email_logo_url(Broken())
        assert url == bundled_default_public_url(EMAIL_HEADER_ROLE)
        assert "<img" in brand_header_html(Broken())

    def test_with_no_session_it_uses_the_approved_default(self):
        assert email_logo_url(None) == bundled_default_public_url(EMAIL_HEADER_ROLE)


# ===========================================================================
# 7. Both renderers, one brand
# ===========================================================================


class TestBothShellsShareTheBrand:
    def test_both_import_the_shared_header(self):
        for relative in (
            "comms/templates/base.py",
            "services/email_templates.py",
        ):
            source = (BACKEND_APP / relative).read_text()
            assert "from app.brand.email import brand_header_html" in source, relative
            assert "{brand_header}" in source, relative

    def test_the_two_shells_render_an_identical_brand_block(self, db):
        from app.comms.templates.base import render_email_shell
        from app.services.email_templates import render_email

        comms = render_email_shell(
            preheader="p", heading="H", body_paragraphs=["b"], db=db,
        )
        legacy = render_email(
            preheader="p", heading="H", body_paragraphs=["b"], db=db,
        )
        block = brand_header_html(db).strip()
        assert block in comms
        assert block in legacy

    def test_neither_shell_still_says_fresh_collective_beside_a_square(self, db):
        from app.comms.templates.base import render_email_shell
        from app.services.email_templates import render_email

        for html in (
            render_email_shell(preheader="p", heading="H", body_paragraphs=["b"]),
            render_email(preheader="p", heading="H", body_paragraphs=["b"]),
        ):
            assert "border-radius:8px" not in html
            assert html.count("<img") == 1

    @pytest.mark.parametrize("event_type", [
        "account.password_reset_requested",
        "gathering.booking.confirmed",
        "purchase.completed",
        "creator.subscription.cancelled",
        "community.post.published",
    ])
    def test_live_templates_resolve_the_admin_override(
        self, db, client, event_type,
    ):
        """Every template threads its session into the shell. A
        template that forgot would silently render the bundled default
        forever, which is exactly the kind of omission nobody notices."""
        from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
        from app.comms.routing.resolver import ResolvedRecipient
        from app.comms.templates.registry import get_template_for

        client.post(
            f"/api/admin/brand-assets/{EMAIL_HEADER_ROLE}",
            files={"file": ("logo.png", _png(), "image/png")},
        )
        expected = email_logo_url(db)
        assert "/platform-artwork/brand/" in expected

        template = get_template_for(event_type, CHANNEL_EMAIL_TRANSACTIONAL)
        payload = template.render(db, None, ResolvedRecipient(
            user_id="u", role_in_event="r", human_reason="h",
            template_context={
                "first_name": "Ada", "reset_url": "https://fc.test/r",
                "gathering_title": "Morning Sit", "collective_name": "Still Water",
                "experience_name": "Life in Alignment",
                "member_url": "https://fc.test/m", "payment_mode": "single",
                "amount_cents": 3780, "currency": "AUD",
                "plan_label": "Creator Portfolio",
                "billing_url": "https://fc.test/b",
                "post_title": "On stillness", "excerpt": "A quiet thought.",
                "view_url": "https://fc.test/v",
            },
        ))
        assert expected in payload.body_html, event_type


# ===========================================================================
# 8. The diagnostic stays unbranded
# ===========================================================================


class TestDiagnosticsStaysPlain:
    def test_the_probe_carries_no_brand_artwork(self, db, make_user):
        from app.comms import Source, emit
        from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
        from app.comms.routing.resolver import ResolvedRecipient
        from app.comms.templates.registry import get_template_for

        user = make_user()
        event = emit(
            db, event_type="diagnostics.provider_probe",
            source_type=Source.FRESH_COLLECTIVE, actor_user_id=user.id,
            payload={"recipient_email": user.email, "note": "n",
                     "triggered_at_iso": "2026-01-01T00:00:00Z"},
        )
        db.flush()
        template = get_template_for(
            "diagnostics.provider_probe", CHANNEL_EMAIL_TRANSACTIONAL,
        )
        html = template.render(db, event, ResolvedRecipient(
            user_id="u", role_in_event="r", human_reason="h",
            template_context={"note": "n", "triggered_at_iso": "2026-01-01T00:00:00Z"},
        )).body_html

        assert "<img" not in html
        assert "/brand/" not in html
        assert "<!DOCTYPE html>" not in html, (
            "the probe is deliberately not rendered through the shell"
        )
