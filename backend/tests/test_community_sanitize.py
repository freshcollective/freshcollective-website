"""SEC-001 — regression tests for ``sanitize_post_body``.

``CommunityPost.body`` is rendered through ``dangerouslySetInnerHTML``
on the community post page + Creator Studio mirror, so the DB row must
already be safe. This module's ``sanitize_post_body`` is the sole
authoritative security boundary — the client-side helper is UX only.

These tests pin the invariants that:

  * Every unsafe tag is stripped (``<script>``, ``<iframe>``, ``<img>``,
    ``<svg>``, ``<object>``, ``<form>``, ``<style>``, ``<link>``).
  * Every event-handler attribute is stripped (``onclick``, ``onerror``,
    ``onload``, ``onfocus``, ``onmouseover``, …).
  * Unsafe URL schemes on the one attribute we do allow — ``<a href>`` —
    are stripped (``javascript:``, ``data:``, ``vbscript:``, ``file:``).
  * The allowed formatting subset survives verbatim.
  * ``rel="noopener noreferrer"`` is always attached to surviving links.
  * The function is idempotent (sanitising twice equals sanitising once).
"""

from __future__ import annotations

import pytest

from app.community.sanitize import sanitize_post_body


# ---------------------------------------------------------------------------
# Unsafe tag removal
# ---------------------------------------------------------------------------


class TestUnsafeTagsStripped:
    def test_script_removed(self):
        html = "<p>ok</p><script>alert(1)</script>"
        cleaned = sanitize_post_body(html)
        assert "<script" not in cleaned.lower()
        assert "alert(1)" not in cleaned

    def test_iframe_removed(self):
        html = '<p>ok</p><iframe src="https://evil"></iframe>'
        cleaned = sanitize_post_body(html)
        assert "<iframe" not in cleaned.lower()

    def test_img_removed(self):
        # <img> is not in the allowlist — the composer never emits it,
        # so any incoming <img> is untrusted (potential xss via onerror).
        html = '<p>ok</p><img src=x onerror="alert(1)">'
        cleaned = sanitize_post_body(html)
        assert "<img" not in cleaned.lower()
        assert "onerror" not in cleaned.lower()
        assert "alert" not in cleaned

    def test_svg_removed(self):
        html = '<svg><script>alert(1)</script></svg><p>ok</p>'
        cleaned = sanitize_post_body(html)
        assert "<svg" not in cleaned.lower()
        assert "<script" not in cleaned.lower()

    def test_object_and_embed_removed(self):
        html = '<object data="x"></object><embed src="y"><p>ok</p>'
        cleaned = sanitize_post_body(html)
        assert "<object" not in cleaned.lower()
        assert "<embed" not in cleaned.lower()

    def test_form_and_input_removed(self):
        html = '<form action="x"><input name="y"></form><p>ok</p>'
        cleaned = sanitize_post_body(html)
        assert "<form" not in cleaned.lower()
        assert "<input" not in cleaned.lower()

    def test_style_and_link_removed(self):
        html = '<style>body{}</style><link rel="stylesheet" href="x"><p>ok</p>'
        cleaned = sanitize_post_body(html)
        assert "<style" not in cleaned.lower()
        assert "<link" not in cleaned.lower()


# ---------------------------------------------------------------------------
# Event-handler attributes on allowed tags
# ---------------------------------------------------------------------------


class TestEventHandlersStripped:
    @pytest.mark.parametrize("handler", [
        "onclick", "onerror", "onload", "onfocus", "onmouseover",
        "onmouseenter", "onchange", "onsubmit", "onkeydown",
    ])
    def test_handler_on_allowed_tag_stripped(self, handler: str):
        html = f'<p {handler}="alert(1)">hello</p>'
        cleaned = sanitize_post_body(html)
        assert handler not in cleaned.lower()
        assert "alert(1)" not in cleaned
        # The tag itself survives.
        assert "<p" in cleaned.lower() and ">hello</p>" in cleaned.lower()

    def test_handler_on_anchor_stripped(self):
        html = '<a href="https://example.com" onclick="alert(1)">link</a>'
        cleaned = sanitize_post_body(html)
        assert "onclick" not in cleaned.lower()
        assert "alert(1)" not in cleaned


# ---------------------------------------------------------------------------
# Anchor URL scheme allowlist
# ---------------------------------------------------------------------------


class TestUnsafeHrefSchemes:
    @pytest.mark.parametrize("bad_href", [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
    ])
    def test_unsafe_scheme_href_stripped(self, bad_href: str):
        html = f'<a href="{bad_href}">click</a>'
        cleaned = sanitize_post_body(html)
        # Either the href is dropped or the whole <a> is neutered.
        assert "javascript" not in cleaned.lower()
        assert "vbscript" not in cleaned.lower()
        assert "alert(1)" not in cleaned
        assert "msgbox" not in cleaned.lower()
        assert "/etc/passwd" not in cleaned

    def test_http_href_survives(self):
        html = '<a href="http://example.com">x</a>'
        cleaned = sanitize_post_body(html)
        assert 'href="http://example.com"' in cleaned

    def test_https_href_survives(self):
        html = '<a href="https://example.com">x</a>'
        cleaned = sanitize_post_body(html)
        assert 'href="https://example.com"' in cleaned


# ---------------------------------------------------------------------------
# Allowed formatting subset survives verbatim
# ---------------------------------------------------------------------------


class TestAllowedFormatting:
    @pytest.mark.parametrize("tag", ["b", "strong", "i", "em", "u", "p", "div", "span"])
    def test_allowed_tag_preserved(self, tag: str):
        html = f"<{tag}>hi</{tag}>"
        cleaned = sanitize_post_body(html)
        assert f"<{tag}>hi</{tag}>" == cleaned

    def test_br_preserved(self):
        cleaned = sanitize_post_body("line one<br>line two")
        # nh3 may serialise as <br> or <br />; accept either.
        assert "<br" in cleaned
        assert "line one" in cleaned
        assert "line two" in cleaned

    def test_paragraph_with_inline_formatting(self):
        html = "<p>hello <strong>world</strong> and <em>friend</em></p>"
        cleaned = sanitize_post_body(html)
        assert cleaned == html


# ---------------------------------------------------------------------------
# rel="noopener noreferrer" auto-attached
# ---------------------------------------------------------------------------


class TestLinkRel:
    def test_rel_attached_to_new_link(self):
        html = '<a href="https://example.com">x</a>'
        cleaned = sanitize_post_body(html)
        assert "noopener" in cleaned
        assert "noreferrer" in cleaned

    def test_rel_attached_when_target_present(self):
        html = '<a href="https://example.com" target="_blank">x</a>'
        cleaned = sanitize_post_body(html)
        assert 'target="_blank"' in cleaned
        assert "noopener" in cleaned
        assert "noreferrer" in cleaned

    def test_creator_supplied_rel_is_normalised(self):
        # A creator posting raw HTML with a hostile ``rel`` (e.g. only
        # "opener") must still get the safe rel injected.
        html = '<a href="https://example.com" rel="opener">x</a>'
        cleaned = sanitize_post_body(html)
        assert "noopener" in cleaned
        assert "noreferrer" in cleaned


# ---------------------------------------------------------------------------
# Idempotence + empty input
# ---------------------------------------------------------------------------


class TestMisc:
    def test_empty_string_returns_empty(self):
        assert sanitize_post_body("") == ""

    def test_none_input_returns_none(self):
        # Preserves the ``not html`` guard's behaviour.
        assert sanitize_post_body(None) is None  # type: ignore[arg-type]

    def test_idempotent(self):
        html = (
            '<p>Hello <strong>world</strong>. '
            '<a href="https://example.com">visit</a></p>'
            '<script>alert(1)</script>'
        )
        once = sanitize_post_body(html)
        twice = sanitize_post_body(once)
        assert once == twice

    def test_plain_text_survives(self):
        cleaned = sanitize_post_body("just some plain text, no tags")
        assert cleaned == "just some plain text, no tags"
