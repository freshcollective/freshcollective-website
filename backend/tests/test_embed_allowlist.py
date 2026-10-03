"""Embed URL extraction and allowlist validation.

``services/embed_validator`` is the gate between what a creator pastes
into an ``embed`` block and what FC stores. The storage model is the
security model: extract the iframe ``src`` if there is one, validate it,
keep **only the URL**, and let the frontend build its own sandboxed
iframe. No creator HTML, script or style is ever persisted, so there is
nothing for a hostile snippet to be rehydrated from.

This file is new with the Neutrino Human Design provider, and covers the
existing providers too — the validator had no tests of its own before,
which is a poor position from which to extend an allowlist.

Neutrino specifics
------------------
Neutrino publishes a ``<script>`` + ``<neutrino-widget>`` loader and a
``<style>`` block alongside its iframe. None of that is used. The
accepted embed is the iframe URL::

    https://neutrinoplatform.com/widget-v2/iframe?type=chart&key=...

The host also serves Neutrino's marketing site, its app and
``loader.js``, so the path is pinned to ``/widget-v2/iframe``. Query
parameters are untouched — the widget is useless without ``type`` and
``key``.
"""

from __future__ import annotations

import pytest

from app.services.embed_validator import (
    EMBED_ALLOWED_HOSTS,
    EMBED_ALLOWED_PATHS,
    EMBED_PROVIDER_NAMES,
    EmbedValidationError,
    extract_and_validate_embed_url,
    extract_embed_src,
)


NEUTRINO_URL = (
    "https://neutrinoplatform.com/widget-v2/iframe"
    "?type=chart&key=7f3a9c21-4b6e-4d2f-9a81-c5e0b7d41f93&hideBrand=true"
)

# The snippet as Neutrino's dashboard hands it over, loader and all.
NEUTRINO_SNIPPET = f'''
<style>
  .neutrino-embed {{ width: 100%; height: 1500px; }}
  @media (min-width: 900px) {{ .neutrino-embed {{ height: 850px; }} }}
</style>
<script src="https://neutrinoplatform.com/widget-v2/loader.js" async></script>
<neutrino-widget type="chart" key="7f3a9c21"></neutrino-widget>
<iframe class="neutrino-embed" src="{NEUTRINO_URL}"
        width="100%" height="850" frameborder="0"
        title="Human Design Chart"></iframe>
'''


# ---------------------------------------------------------------------------
# Neutrino — the new provider
# ---------------------------------------------------------------------------


class TestNeutrinoHumanDesign:
    def test_the_direct_widget_url_is_accepted_unchanged(self):
        assert extract_and_validate_embed_url(NEUTRINO_URL) == NEUTRINO_URL

    def test_the_query_string_is_preserved(self):
        """``type`` and ``key`` identify the chart; ``hideBrand`` is the
        creator's display choice. Dropping any of them would store a URL
        that renders the wrong thing, or nothing."""
        stored = extract_and_validate_embed_url(NEUTRINO_URL)
        assert "type=chart" in stored
        assert "key=7f3a9c21-4b6e-4d2f-9a81-c5e0b7d41f93" in stored
        assert "hideBrand=true" in stored

    def test_the_full_snippet_yields_only_the_iframe_src(self):
        """The whole point of the storage model. What Neutrino supplies
        includes a loader script and a style block; what FC keeps is one
        URL."""
        stored = extract_and_validate_embed_url(NEUTRINO_SNIPPET)

        assert stored == NEUTRINO_URL
        for fragment in ("<script", "<style", "<neutrino-widget", "<iframe", "loader.js"):
            assert fragment not in stored, f"{fragment} survived into storage"

    def test_the_loader_script_url_is_not_itself_embeddable(self):
        """A creator pasting the loader URL instead of the iframe URL
        gets a refusal, not a framed script."""
        with pytest.raises(EmbedValidationError) as exc:
            extract_and_validate_embed_url(
                "https://neutrinoplatform.com/widget-v2/loader.js",
            )
        assert "path" in str(exc.value).lower()

    @pytest.mark.parametrize("path", [
        "/",
        "/app/dashboard",
        "/widget-v2",
        "/widget-v2/other",
        "/login",
    ])
    def test_other_paths_on_the_same_host_are_rejected(self, path):
        """Path restriction is implemented, so a Collective page cannot
        frame the rest of Neutrino through a chart block."""
        with pytest.raises(EmbedValidationError):
            extract_and_validate_embed_url(f"https://neutrinoplatform.com{path}")

    def test_a_path_that_merely_starts_with_the_allowed_one_is_rejected(self):
        """``/widget-v2/iframexyz`` shares a prefix with the allowed path
        and is a different path."""
        with pytest.raises(EmbedValidationError):
            extract_and_validate_embed_url(
                "https://neutrinoplatform.com/widget-v2/iframexyz?type=chart",
            )

    @pytest.mark.parametrize("suffix", [
        "/v3",
        "/chart",
        "/../app",
        "/anything",
    ])
    def test_a_descendant_path_is_rejected(self, suffix):
        """The match is exact, not a prefix. There is no evidence
        Neutrino serves anything beneath the widget path, and a prefix
        rule would admit every future route under it sight unseen."""
        with pytest.raises(EmbedValidationError):
            extract_and_validate_embed_url(
                f"https://neutrinoplatform.com/widget-v2/iframe{suffix}?type=chart",
            )

    def test_the_exact_path_with_a_trailing_slash_is_accepted(self):
        """The same resource. Refusing a URL that works in the browser
        would be a confusing rejection rather than a safer one, and a
        trailing slash cannot reach a different path."""
        url = "https://neutrinoplatform.com/widget-v2/iframe/?type=chart"
        assert extract_and_validate_embed_url(url) == url

    def test_the_stored_url_is_never_rewritten(self):
        """Normalisation happens for the comparison only. What a creator
        pasted is what gets stored, trailing slash and all."""
        for url in (
            "https://neutrinoplatform.com/widget-v2/iframe?type=chart",
            "https://neutrinoplatform.com/widget-v2/iframe/?type=chart",
        ):
            assert extract_and_validate_embed_url(url) == url

    def test_http_is_rejected(self):
        with pytest.raises(EmbedValidationError) as exc:
            extract_and_validate_embed_url(
                "http://neutrinoplatform.com/widget-v2/iframe?type=chart",
            )
        assert "https" in str(exc.value).lower()

    @pytest.mark.parametrize("host", [
        "neutrinoplatform.com.evil.example",
        "neutrinoplatform.com.attacker.test",
        "notneutrinoplatform.com",
        "neutrinoplatform.co",
        "evil-neutrinoplatform.com",
    ])
    def test_deceptive_hosts_are_rejected(self, host):
        """Suffix match on a dot boundary, never substring. Each of these
        contains or resembles the allowed host and is a different
        origin."""
        with pytest.raises(EmbedValidationError) as exc:
            extract_and_validate_embed_url(
                f"https://{host}/widget-v2/iframe?type=chart",
            )
        assert "allowlist" in str(exc.value).lower()

    def test_a_subdomain_is_accepted_and_still_path_pinned(self):
        """Suffix matching admits ``www.``; the path policy follows the
        matched allowlist entry, so it still applies."""
        ok = "https://www.neutrinoplatform.com/widget-v2/iframe?type=chart"
        assert extract_and_validate_embed_url(ok) == ok

        with pytest.raises(EmbedValidationError):
            extract_and_validate_embed_url(
                "https://www.neutrinoplatform.com/app",
            )

    def test_the_host_and_the_name_are_both_registered(self):
        assert "neutrinoplatform.com" in EMBED_ALLOWED_HOSTS
        assert "Neutrino Human Design" in EMBED_PROVIDER_NAMES
        assert EMBED_ALLOWED_PATHS["neutrinoplatform.com"] == (
            "/widget-v2/iframe",
        )

    def test_the_refusal_says_the_match_is_exact(self):
        """So a creator who pasted a near-miss knows the rule, rather
        than guessing that a sub-path might work."""
        with pytest.raises(EmbedValidationError) as exc:
            extract_and_validate_embed_url(
                "https://neutrinoplatform.com/widget-v2/iframe/v3",
            )
        assert "exactly" in str(exc.value)
        assert "/widget-v2/iframe" in str(exc.value)


# ---------------------------------------------------------------------------
# The rejection message
# ---------------------------------------------------------------------------


class TestTheSupportedProvidersMessage:
    def test_it_names_neutrino(self):
        with pytest.raises(EmbedValidationError) as exc:
            extract_and_validate_embed_url("https://example.com/thing")
        assert "Neutrino Human Design" in str(exc.value)

    def test_it_is_derived_from_the_provider_list(self):
        """It used to be a hand-written literal, which is how a message
        drifts from the allowlist it describes."""
        with pytest.raises(EmbedValidationError) as exc:
            extract_and_validate_embed_url("https://example.com/thing")
        message = str(exc.value)
        for name in EMBED_PROVIDER_NAMES:
            assert name in message, f"{name} missing from the refusal"


# ---------------------------------------------------------------------------
# Existing providers — unchanged
# ---------------------------------------------------------------------------


class TestTheProvidersThatWereAlreadyAllowed:
    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://youtube-nocookie.com/embed/abc",
        "https://youtu.be/abc",
        "https://player.vimeo.com/video/123456",
        "https://fast.wistia.net/embed/iframe/abc",
        "https://www.loom.com/embed/abc",
        "https://docs.google.com/forms/d/e/abc/viewform?embedded=true",
        "https://forms.gle/abc",
        "https://form.typeform.com/to/abc",
        "https://calendly.com/someone/30min",
        "https://open.spotify.com/embed/episode/abc",
        "https://w.soundcloud.com/player/?url=https%3A//api.soundcloud.com/tracks/1",
    ])
    def test_each_is_still_accepted(self, url):
        assert extract_and_validate_embed_url(url) == url

    def test_no_existing_provider_gained_a_path_restriction(self):
        """Only Neutrino is path-pinned. A restriction added to a live
        provider would start rejecting embeds already in the database."""
        assert set(EMBED_ALLOWED_PATHS) == {"neutrinoplatform.com"}

    def test_deep_paths_on_unrestricted_providers_still_work(self):
        """The exact-match rule must not leak to hosts that have no
        entry — these providers legitimately use deep paths."""
        for url in (
            "https://docs.google.com/forms/d/e/1FAIpQLSc/viewform?embedded=true",
            "https://calendly.com/someone/30min/2026-10-03T10:00:00",
            "https://player.vimeo.com/video/123456?h=abc&badge=0",
        ):
            assert extract_and_validate_embed_url(url) == url

    @pytest.mark.parametrize("url", [
        "https://calendly.com.evil.example/x",
        "https://youtube.com.attacker.test/embed/abc",
        "https://evil.example/embed",
    ])
    def test_deceptive_and_unknown_hosts_are_still_rejected(self, url):
        with pytest.raises(EmbedValidationError):
            extract_and_validate_embed_url(url)

    def test_http_is_still_rejected_for_an_allowed_host(self):
        with pytest.raises(EmbedValidationError):
            extract_and_validate_embed_url("http://calendly.com/someone/30min")


# ---------------------------------------------------------------------------
# Extraction — nothing but a URL survives
# ---------------------------------------------------------------------------


class TestOnlyTheUrlIsEverStored:
    def test_a_plain_iframe_snippet_is_reduced_to_its_src(self):
        raw = '<iframe src="https://calendly.com/a/b" width="100%"></iframe>'
        assert extract_embed_src(raw) == "https://calendly.com/a/b"

    def test_an_iframe_with_no_src_is_refused(self):
        with pytest.raises(EmbedValidationError) as exc:
            extract_embed_src('<iframe width="100%"></iframe>')
        assert "src" in str(exc.value).lower()

    def test_a_script_only_snippet_is_refused(self):
        """There is no iframe to extract from, and the input is not a
        URL. It must not be stored as content."""
        with pytest.raises(EmbedValidationError):
            extract_embed_src(
                '<script src="https://neutrinoplatform.com/widget-v2/loader.js"></script>'
            )

    def test_an_empty_value_is_refused(self):
        with pytest.raises(EmbedValidationError):
            extract_embed_src("   ")

    @pytest.mark.parametrize("raw", [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "//neutrinoplatform.com/widget-v2/iframe",
        "neutrinoplatform.com/widget-v2/iframe",
    ])
    def test_non_http_schemes_and_bare_hosts_are_refused(self, raw):
        with pytest.raises(EmbedValidationError):
            extract_embed_src(raw)

    def test_surrounding_whitespace_is_trimmed(self):
        assert extract_embed_src(f"  {NEUTRINO_URL}  ") == NEUTRINO_URL
