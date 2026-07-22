"""Unit tests for the button block caption/style validator.

Locks in three shapes for the ``caption`` column:

  1. Legacy style names — ``primary`` | ``secondary`` | ``outline`` |
     ``subtle`` — kept for backward compatibility with pre-palette
     buttons.
  2. Modern JSON envelope — ``{"style": ..., "colour": ...}`` — must
     accept palette-linked roles and custom hex overrides and reject
     everything else.
  3. Empty / unknown legacy — falls back to ``primary``.

Also covers URL + text validation for completeness.
"""

from __future__ import annotations

import json

import pytest

from app.services.button_validator import (
    ButtonValidationError,
    normalise_button_style,
    normalise_new_tab,
    validate_button_text,
    validate_button_url,
)


class TestLegacyStyles:
    @pytest.mark.parametrize("style", ["primary", "secondary", "outline", "subtle"])
    def test_each_legacy_style_passes_through(self, style: str) -> None:
        assert normalise_button_style(style) == style

    def test_legacy_style_is_lowercased_and_trimmed(self) -> None:
        assert normalise_button_style("  PRIMARY  ") == "primary"

    def test_unknown_legacy_string_rejected(self) -> None:
        with pytest.raises(ButtonValidationError):
            normalise_button_style("gigantic")

    def test_empty_and_none_fall_back_to_primary(self) -> None:
        assert normalise_button_style(None) == "primary"
        assert normalise_button_style("") == "primary"
        assert normalise_button_style("   ") == "primary"


class TestModernJsonEnvelope:
    @pytest.mark.parametrize("style", ["filled", "outline", "text"])
    def test_each_modern_style_accepted(self, style: str) -> None:
        out = normalise_button_style(json.dumps({"style": style, "colour": "palette:primary"}))
        parsed = json.loads(out)
        assert parsed == {"style": style, "colour": "palette:primary"}

    @pytest.mark.parametrize(
        "role", ["primary", "secondary", "accent", "background"],
    )
    def test_each_palette_role_accepted(self, role: str) -> None:
        out = normalise_button_style(json.dumps({"style": "filled", "colour": f"palette:{role}"}))
        parsed = json.loads(out)
        assert parsed["colour"] == f"palette:{role}"

    def test_custom_hex_accepted(self) -> None:
        out = normalise_button_style(
            json.dumps({"style": "outline", "colour": "custom:#3A6B7A"})
        )
        parsed = json.loads(out)
        assert parsed == {"style": "outline", "colour": "custom:#3A6B7A"}

    def test_short_hex_accepted(self) -> None:
        out = normalise_button_style(
            json.dumps({"style": "text", "colour": "custom:#abc"})
        )
        parsed = json.loads(out)
        assert parsed["colour"] == "custom:#abc"

    def test_stray_fields_are_stripped(self) -> None:
        # The re-serialised caption should only contain style + colour.
        out = normalise_button_style(
            json.dumps({"style": "filled", "colour": "palette:accent", "hijack": "yes"})
        )
        parsed = json.loads(out)
        assert set(parsed.keys()) == {"style", "colour"}

    def test_bad_style_rejected(self) -> None:
        with pytest.raises(ButtonValidationError):
            normalise_button_style(json.dumps({"style": "weird", "colour": "palette:primary"}))

    def test_bad_role_rejected(self) -> None:
        with pytest.raises(ButtonValidationError):
            normalise_button_style(json.dumps({"style": "filled", "colour": "palette:mystery"}))

    def test_legacy_colour_key_rejected_inside_envelope(self) -> None:
        # ``palette:*`` and ``custom:*`` are the only accepted forms;
        # legacy chip keys never appear in the JSON envelope.
        with pytest.raises(ButtonValidationError):
            normalise_button_style(json.dumps({"style": "filled", "colour": "teal"}))

    def test_bad_hex_rejected(self) -> None:
        with pytest.raises(ButtonValidationError):
            normalise_button_style(json.dumps({"style": "outline", "colour": "custom:not-hex"}))

    def test_javascript_scheme_rejected(self) -> None:
        # Custom colour values must be a hex — no URL smuggling.
        with pytest.raises(ButtonValidationError):
            normalise_button_style(json.dumps({"style": "outline", "colour": "custom:javascript:alert(1)"}))

    def test_malformed_json_rejected(self) -> None:
        with pytest.raises(ButtonValidationError):
            normalise_button_style("{not json")

    def test_json_array_rejected(self) -> None:
        with pytest.raises(ButtonValidationError):
            normalise_button_style('["filled", "palette:primary"]')


class TestButtonText:
    def test_trims_and_returns(self) -> None:
        assert validate_button_text("  Hello  ") == "Hello"

    def test_empty_rejected(self) -> None:
        with pytest.raises(ButtonValidationError):
            validate_button_text("")

    def test_too_long_rejected(self) -> None:
        with pytest.raises(ButtonValidationError):
            validate_button_text("x" * 81)


class TestNewTab:
    def test_valid_values(self) -> None:
        assert normalise_new_tab("new_tab") == "new_tab"
        assert normalise_new_tab("same_tab") == "same_tab"

    def test_unknown_normalises_to_none(self) -> None:
        assert normalise_new_tab("mystery") is None

    def test_empty_normalises_to_none(self) -> None:
        assert normalise_new_tab("") is None
        assert normalise_new_tab(None) is None


class TestButtonUrl:
    def test_https_ok(self) -> None:
        assert validate_button_url("https://example.com") == "https://example.com"

    def test_internal_path_ok(self) -> None:
        assert validate_button_url("/spaces/embody") == "/spaces/embody"

    def test_mailto_ok(self) -> None:
        assert validate_button_url("mailto:x@example.com") == "mailto:x@example.com"

    def test_javascript_rejected(self) -> None:
        with pytest.raises(ButtonValidationError):
            validate_button_url("javascript:alert(1)")

    def test_protocol_relative_rejected(self) -> None:
        with pytest.raises(ButtonValidationError):
            validate_button_url("//evil.com")

    def test_empty_rejected(self) -> None:
        with pytest.raises(ButtonValidationError):
            validate_button_url("")
