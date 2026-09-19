"""Admin-editable email copy — declarations, merge fields, resolution.

Fresh Collective admins can rewrite the *voice* of selected emails from
World Management. They can never reach a link, an amount, a date, an
access state or a security instruction.

That guarantee is structural rather than enforced by validation: a
template declares only the slots that are safe to rewrite, and anything
it does not declare simply has no field through which it can be
reached. There is deliberately no generic "body" — the templates in
this codebase interleave pure voice with generated fact inside a single
rendered paragraph list, so one body field would hand both to an admin
at once.

How a slot is resolved
----------------------

    override (DB)  →  code default  →  merge-field substitution  →  text

Both branches end in the same substitution step, so a default and an
override travel an identical path. A preview cannot diverge from a real
send, and a default is free to contain merge fields of its own.

Defaults therefore live here as ``{{field}}``-templated strings rather
than as f-strings inside the template classes. The template asks for a
slot and receives finished plain text.

Safety properties
-----------------

* **No raw HTML, structurally.** Slots return plain text, which
  ``render_email_shell`` escapes along with everything else. There is
  no code path that renders admin input as markup.
* **No code execution.** Substitution is a regex over a dict. Not
  Jinja, not ``str.format`` (which exposes attribute traversal), not
  ``eval``.
* **Fails safe.** A malformed override can never break a send: the
  resolver logs it and falls back to the code default. Validation at
  save time means such a row should not exist, but sending is not the
  place to discover that it does.
"""

from __future__ import annotations

import contextvars
import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

EDITABLE = "editable"        # every declared slot is open
PARTIAL = "partial"          # framing open, fact-bearing lines stay in code
SYSTEM = "system"            # nothing editable; listed read-only

ALL_CLASSIFICATIONS = (EDITABLE, PARTIAL, SYSTEM)

# Admin-facing grouping in the World Management list.
CATEGORY_ACCOUNT_LABEL = "Account"
CATEGORY_GATHERINGS_LABEL = "Gatherings"
CATEGORY_COMMUNITY_LABEL = "Community"
CATEGORY_MONEY_LABEL = "Purchases & billing"


# Subject lines are plain text and must stay short enough to survive an
# inbox list. Generous, but not unbounded.
SUBJECT_MAX_LENGTH = 120
SLOT_MAX_LENGTH = 2000

# ``{{ field_name }}`` — snake_case only, optional inner whitespace.
_FIELD_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")

# Anything that looks like markup is refused at save time. The shell
# would escape it harmlessly, but a member seeing a literal "<b>" is a
# defect, and an admin typing one deserves to be told immediately.
_MARKUP_RE = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------------------
# Merge fields
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MergeField:
    """One placeholder an admin may use.

    ``name`` is the stable, member-facing vocabulary shown in the admin
    UI. ``source_key`` is the internal ``template_context`` key it reads
    from. The indirection means an internal rename never invalidates a
    saved override.
    """

    name: str
    source_key: str
    sample: str
    description: str = ""


def _fields_by_name(fields: tuple[MergeField, ...]) -> dict[str, MergeField]:
    return {f.name: f for f in fields}


# ---------------------------------------------------------------------------
# Slots
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EditableSlot:
    """One unit of copy an admin may rewrite.

    ``default`` is the Fresh Collective wording, itself a
    ``{{field}}``-templated string. ``required_fields`` names merge
    fields the slot must keep to stay truthful — an override that drops
    one is refused.
    """

    slot_id: str
    label: str
    default: str
    help_text: str = ""
    required_fields: tuple[str, ...] = ()
    multiline: bool = True
    max_length: int = SLOT_MAX_LENGTH

    def fingerprint(self) -> str:
        """Hash of the code default, stamped onto an override at save.

        When a future deploy improves the default this stops matching,
        which is how the admin UI knows to say "the Fresh Collective
        default has changed since you customised this".
        """
        return hashlib.sha256(self.default.encode("utf-8")).hexdigest()[:32]


SUBJECT_SLOT_ID = "subject"


# ---------------------------------------------------------------------------
# Template declarations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemplateDeclaration:
    """Everything the admin surface needs to know about one email."""

    template_key: str
    event_type: str
    display_name: str
    category: str
    audience: str
    classification: str
    slots: tuple[EditableSlot, ...] = ()
    merge_fields: tuple[MergeField, ...] = ()
    # Notes rendered in the editor beside the locked items, so an admin
    # can see what the system owns rather than hunting for a field.
    locked_notes: tuple[str, ...] = ()

    @property
    def subject_slot(self) -> EditableSlot | None:
        return self.slot(SUBJECT_SLOT_ID)

    @property
    def subject_editable(self) -> bool:
        return self.subject_slot is not None

    @property
    def is_editable(self) -> bool:
        return self.classification in (EDITABLE, PARTIAL)

    def slot(self, slot_id: str) -> EditableSlot | None:
        for s in self.slots:
            if s.slot_id == slot_id:
                return s
        return None

    def field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.merge_fields)


_DECLARATIONS: dict[str, TemplateDeclaration] = {}


def declare(decl: TemplateDeclaration) -> TemplateDeclaration:
    if decl.classification not in ALL_CLASSIFICATIONS:
        raise ValueError(
            f"{decl.template_key}: unknown classification "
            f"{decl.classification!r}"
        )
    if decl.template_key in _DECLARATIONS:
        raise ValueError(f"duplicate declaration for {decl.template_key}")
    if decl.classification == SYSTEM and decl.slots:
        raise ValueError(
            f"{decl.template_key}: system-controlled templates must declare "
            "no editable slots — an undeclared slot is unreachable, which is "
            "the whole guarantee"
        )
    seen: set[str] = set()
    known = set(decl.field_names())
    for s in decl.slots:
        if s.slot_id in seen:
            raise ValueError(f"{decl.template_key}: duplicate slot {s.slot_id!r}")
        seen.add(s.slot_id)
        # A default that references a field the template cannot supply
        # would render as an empty string in production. Catch at import.
        for used in _FIELD_RE.findall(s.default):
            if used not in known:
                raise ValueError(
                    f"{decl.template_key}.{s.slot_id}: default uses "
                    f"{{{{{used}}}}} which is not in the merge-field whitelist"
                )
        for req in s.required_fields:
            if req not in known:
                raise ValueError(
                    f"{decl.template_key}.{s.slot_id}: required field "
                    f"{req!r} is not in the merge-field whitelist"
                )
    _DECLARATIONS[decl.template_key] = decl
    return decl


def get_declaration(template_key: str) -> TemplateDeclaration | None:
    return _DECLARATIONS.get(template_key)


def all_declarations() -> tuple[TemplateDeclaration, ...]:
    return tuple(
        sorted(_DECLARATIONS.values(), key=lambda d: (d.category, d.display_name))
    )


def reset_declarations() -> None:
    """Tests only."""
    _DECLARATIONS.clear()


# ---------------------------------------------------------------------------
# Substitution
# ---------------------------------------------------------------------------


def substitute(
    text: str,
    decl: TemplateDeclaration,
    context: Mapping[str, Any],
) -> str:
    """Replace ``{{field}}`` with values from ``context``.

    A regex over a dict — no expression language, so there is nothing
    to escape from. An unknown field (which validation should already
    have refused) and a field with no value both render as an empty
    string: a literal ``{{…}}`` reaching a member's inbox is worse than
    a slightly shorter sentence.
    """
    by_name = _fields_by_name(decl.merge_fields)

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        mf = by_name.get(name)
        if mf is None:
            logger.warning(
                "editable copy: unknown merge field {{%s}} in %s — rendering "
                "as empty", name, decl.template_key,
            )
            return ""
        value = context.get(mf.source_key)
        return "" if value is None else str(value)

    out = _FIELD_RE.sub(_replace, text)

    # Defence in depth: strip anything still wearing braces. A
    # malformed placeholder — ``{{who.__class__}}``, an unclosed brace —
    # does not match the field pattern, so it would otherwise survive
    # verbatim into a member's inbox. Validation refuses these at save
    # time; this is the belt to that pair of braces.
    leftover = re.sub(r"\{\{.*?\}\}", "", out, flags=re.S)
    if leftover != out:
        logger.warning(
            "editable copy: stripped a malformed placeholder while rendering "
            "%s", decl.template_key,
        )
        out = leftover

    # Collapse whitespace left behind by an empty substitution so copy
    # never renders with a double space or a stranded comma-space.
    return re.sub(r"[ \t]{2,}", " ", out).strip()


# ---------------------------------------------------------------------------
# Validation — used by the admin save path AND by preview
# ---------------------------------------------------------------------------


class SlotValidationError(ValueError):
    """Raised with a list of human-readable problems."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def validate_slot_value(
    decl: TemplateDeclaration, slot_id: str, value: str,
) -> list[str]:
    """Return a list of problems with a proposed override. Empty = valid."""
    errors: list[str] = []

    if not decl.is_editable:
        return [
            f"{decl.display_name} is system-controlled and has no editable copy."
        ]

    slot = decl.slot(slot_id)
    if slot is None:
        errors.append(
            f"Unknown field {slot_id!r}. This email exposes: "
            f"{', '.join(s.slot_id for s in decl.slots) or '(none)'}."
        )
        return errors

    if not value or not value.strip():
        errors.append(f"{slot.label} cannot be empty.")
        return errors

    limit = SUBJECT_MAX_LENGTH if slot_id == SUBJECT_SLOT_ID else slot.max_length
    if len(value) > limit:
        errors.append(
            f"{slot.label} is {len(value)} characters; the limit is {limit}."
        )

    if _MARKUP_RE.search(value):
        errors.append(
            f"{slot.label} must be plain text — HTML tags are not allowed. "
            "Formatting is handled by the Fresh Collective email design."
        )

    if slot_id == SUBJECT_SLOT_ID and ("\n" in value or "\r" in value):
        errors.append("A subject line must be a single line.")

    known = set(decl.field_names())
    used = set(_FIELD_RE.findall(value))
    for name in sorted(used - known):
        errors.append(
            f"{{{{{name}}}}} is not available in this email. Available: "
            + (", ".join(f"{{{{{n}}}}}" for n in decl.field_names()) or "none")
            + "."
        )
    for req in slot.required_fields:
        if req not in used:
            errors.append(
                f"{slot.label} must keep {{{{{req}}}}} — the email would "
                "otherwise lose information the member needs."
            )

    # A stray single brace is almost always a typo for a placeholder.
    stripped = _FIELD_RE.sub("", value)
    if "{{" in stripped or "}}" in stripped:
        errors.append(
            f"{slot.label} has an unclosed or malformed {{{{placeholder}}}}."
        )

    return errors


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


@dataclass
class SlotResolver:
    """Resolves slots for one render.

    Overrides are loaded once per render and held here, so a template
    with six slots costs one query rather than six. Constructed with no
    overrides (the default) it behaves exactly as the code did before
    this feature existed, which is what keeps the no-override path
    byte-identical.
    """

    decl: TemplateDeclaration
    context: Mapping[str, Any] = field(default_factory=dict)
    overrides: Mapping[str, str] = field(default_factory=dict)

    def raw(self, slot_id: str) -> str:
        """The un-substituted string that will be used — override when
        one is present and usable, code default otherwise."""
        slot = self.decl.slot(slot_id)
        if slot is None:
            raise KeyError(
                f"{self.decl.template_key} declares no slot {slot_id!r}"
            )
        candidate = self.overrides.get(slot_id)
        if candidate is None:
            return slot.default
        problems = validate_slot_value(self.decl, slot_id, candidate)
        if problems:
            # Fail safe. Validation at save time should mean we never
            # get here; if we do, a member still receives correct
            # Fresh Collective copy and the operator gets a loud log.
            logger.error(
                "editable copy: stored override for %s.%s is invalid (%s) — "
                "falling back to the code default",
                self.decl.template_key, slot_id, "; ".join(problems),
            )
            return slot.default
        return candidate

    def text(self, slot_id: str) -> str:
        """Finished plain text, merge fields substituted."""
        return substitute(self.raw(slot_id), self.decl, self.context)

    def uses_override(self, slot_id: str) -> bool:
        slot = self.decl.slot(slot_id)
        return (
            slot is not None
            and slot_id in self.overrides
            and self.raw(slot_id) != slot.default
        )


def load_overrides(db: Any, template_key: str) -> dict[str, str]:
    """Read every stored override for a template. Never raises — a
    database problem must not stop an email going out."""
    try:
        from app.models.communication_template_override import (
            CommunicationTemplateOverride,
        )
        rows = (
            db.query(CommunicationTemplateOverride)
            .filter(CommunicationTemplateOverride.template_key == template_key)
            .all()
        )
        return {r.slot_id: r.value for r in rows}
    except Exception:
        logger.exception(
            "editable copy: could not load overrides for %s — using Fresh "
            "Collective defaults", template_key,
        )
        return {}


# Draft overrides for a preview render. Set for the duration of one
# admin preview request and read by ``resolver_for`` instead of the
# database, so a preview exercises the real template through the real
# shell without a preview-specific rendering path — which is how
# previews drift from production in the first place. A ContextVar
# rather than a module global so concurrent requests cannot see each
# other's drafts.
_preview_overrides: contextvars.ContextVar[dict[str, dict[str, str]] | None] = (
    contextvars.ContextVar("fc_preview_overrides", default=None)
)


class preview_overrides:
    """Context manager supplying draft overrides for one render.

        with preview_overrides({template_key: {"heading": "…"}}):
            template.render(...)
    """

    def __init__(self, drafts: dict[str, dict[str, str]]) -> None:
        self._drafts = drafts
        self._token: Any = None

    def __enter__(self) -> "preview_overrides":
        self._token = _preview_overrides.set(self._drafts)
        return self

    def __exit__(self, *exc: Any) -> None:
        _preview_overrides.reset(self._token)


def resolver_for(
    db: Any,
    template_key: str,
    context: Mapping[str, Any],
) -> SlotResolver:
    """The entry point templates call.

    ``db`` may be ``None`` — several templates are rendered in tests and
    in preview without a session, and they must still produce the code
    defaults.
    """
    decl = get_declaration(template_key)
    if decl is None:
        raise KeyError(f"no editable declaration for {template_key!r}")

    drafts = _preview_overrides.get()
    if drafts is not None:
        # Preview: show exactly the drafts supplied, never a mix of
        # draft and saved.
        return SlotResolver(
            decl=decl, context=context,
            overrides=dict(drafts.get(template_key, {})),
        )

    overrides = load_overrides(db, template_key) if db is not None else {}
    return SlotResolver(decl=decl, context=context, overrides=overrides)


__all__ = [
    "EDITABLE",
    "PARTIAL",
    "SYSTEM",
    "SUBJECT_MAX_LENGTH",
    "SUBJECT_SLOT_ID",
    "EditableSlot",
    "MergeField",
    "SlotResolver",
    "SlotValidationError",
    "TemplateDeclaration",
    "all_declarations",
    "declare",
    "get_declaration",
    "load_overrides",
    "preview_overrides",
    "reset_declarations",
    "resolver_for",
    "substitute",
    "validate_slot_value",
]
