"""Codebase-contract regression: the paid-creator pre-checkout page
must not carry prototype language now that Stripe is live.

Fixed 2026-09-16 after the live external-creator test found the
page still said "Payment will happen here" / "PROTOTYPE PREVIEW"
/ "When Stripe is connected..." / "Nothing is charged in this
prototype...". This test locks the fix so a future edit can't
regress the copy.
"""

from __future__ import annotations

from pathlib import Path


_FRONTEND_ROOT = Path(__file__).resolve().parent.parent.parent / "frontend"
_CHECKOUT_CREATOR = _FRONTEND_ROOT / "src/app/checkout/creator/page.tsx"


_BANNED_STRINGS = [
    "Payment will happen here",
    "PROTOTYPE PREVIEW",
    "Prototype preview",
    "When Stripe is connected",
    "Nothing is charged in this prototype",
]


def test_creator_prechecko_page_has_no_prototype_copy():
    """The user-visible copy MUST NOT include any of the prototype
    strings. Comments/docstrings that reference the term historically
    are fine — the ban is on strings that would render to the
    visitor."""
    assert _CHECKOUT_CREATOR.exists(), f"Missing surface: {_CHECKOUT_CREATOR}"
    source = _CHECKOUT_CREATOR.read_text(encoding="utf-8")
    for banned in _BANNED_STRINGS:
        # Allow the string inside a JS/TS block comment (``/* ... */``
        # or ``// ...``). Cheapest check: only flag the string when
        # it appears inside JSX-quoted content (i.e., not on a comment
        # line). Approximation — false negatives are acceptable for a
        # codebase-contract test; false positives would block a
        # legitimate rewrite.
        for line in source.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            assert banned not in line, (
                f"checkout/creator/page.tsx: prototype copy {banned!r} "
                "reappeared in a non-comment line. Stripe is live; "
                "this page must not describe itself as a prototype."
            )


def test_creator_prechecko_page_uses_secure_checkout_framing():
    """Positive assertion — the new copy is present. Guards against
    the file being blanked / left copy-less after a merge."""
    assert _CHECKOUT_CREATOR.exists()
    source = _CHECKOUT_CREATOR.read_text(encoding="utf-8")
    assert "Secure checkout" in source
    assert "Review your plan" in source
    assert "You" in source and "Stripe" in source, (
        "checkout/creator/page.tsx: expected the truthful "
        "'You\u2019ll complete payment securely with Stripe.' body "
        "copy to be present."
    )
