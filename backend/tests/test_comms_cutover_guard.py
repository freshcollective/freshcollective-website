"""Guard against half-finished comms cutovers.

The booking-confirmation outage had a specific shape. ``d605535``:

1. added a ``_rollout_is_live`` guard so the legacy sender stood down
   once the topic went live;
2. wrote a replacement comms emit helper;
3. **never called it.**

Nothing failed. No test broke. Members simply stopped receiving an
email for three and a half weeks, and it was only caught by a human
manually booking a gathering and noticing the silence.

Two layers here, because one is not enough.

Layer 1 — *an emit exists*
    Every registered event type that is live AND has a resolver AND has
    a template should have an emit call somewhere in ``app/``.
    Cheap, and catches "we built the receiving half and forgot the
    sending half entirely".

Layer 2 — *the emit is reachable*
    Layer 1 would **not** have caught the real bug: the dead helper did
    contain ``event_type="gathering.booking.confirmed"``, so the string
    was present and the check would have passed. What was missing was a
    *call*. Layer 2 asserts that the function containing each emit is
    either invoked somewhere else in the package or is itself a
    decorated route handler.

On brittleness
--------------

Real reachability analysis means a full call graph, and Python's
dynamic dispatch makes that unreliable. This is deliberately a
one-hop, name-based approximation, chosen because it exactly matches
the failure mode observed and because its failure direction is safe:
it can produce a false *alarm* (a genuinely-wired emit reached in some
way this cannot see), never a false *pass* for a function nobody
calls. A false alarm is a loud prompt to add an entry to
``KNOWN_UNREACHABLE`` with a reason — a deliberate decision, recorded.

Both layers resolve module-level string constants, because the emit
sites in this codebase overwhelmingly use ``event_type=_EVENT_TYPE``
rather than a bare literal. A literal-only scan reports false gaps for
every one of them.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

import app.comms.templates  # noqa: F401 — registers templates
import app.comms.routing.resolvers  # noqa: F401 — registers resolvers
from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL, CHANNEL_IN_APP
from app.comms.registry import registered_event_types
from app.comms.rollout import is_event_live
from app.comms.routing.resolver import get_resolver_for
from app.comms.templates.registry import get_template_for


APP_ROOT = pathlib.Path(__file__).resolve().parent.parent / "app"


# Event types that are live with full resolver/template coverage but
# deliberately have no emit yet. Empty today. Adding one is a product
# decision and belongs here with a reason, not silently.
KNOWN_UNEMITTED: dict[str, str] = {}

# Emit sites that exist but that this one-hop analysis cannot see a
# call for. Empty today. An entry here means "verified wired by hand".
KNOWN_UNREACHABLE: dict[str, str] = {}


def _module_constants(tree: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def _event_type_of(call: ast.Call, consts: dict[str, str]) -> str | None:
    """The event type this call emits, if it is an emit call."""
    for kw in call.keywords:
        if kw.arg != "event_type":
            continue
        value = kw.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        if isinstance(value, ast.Name):
            return consts.get(value.id)
    return None


@pytest.fixture(scope="module")
def scan() -> tuple[dict[str, set[str]], set[str], set[str]]:
    """(emit_sites, called_names, decorated_fns) across ``app/``.

    ``emit_sites`` maps event type → names of the functions whose body
    contains an emit for it (``"<module>"`` for a top-level emit).
    """
    emit_sites: dict[str, set[str]] = {}
    called: set[str] = set()
    decorated: set[str] = set()

    for path in APP_ROOT.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        consts = _module_constants(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    called.add(func.id)
                elif isinstance(func, ast.Attribute):
                    called.add(func.attr)

        functions = [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        for fn in functions:
            if fn.decorator_list:
                decorated.add(fn.name)
            for node in ast.walk(fn):
                if isinstance(node, ast.Call):
                    et = _event_type_of(node, consts)
                    if et:
                        emit_sites.setdefault(et, set()).add(fn.name)

        # Emits at module level, outside any function.
        enclosed = {id(n) for fn in functions for n in ast.walk(fn)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and id(node) not in enclosed:
                et = _event_type_of(node, consts)
                if et:
                    emit_sites.setdefault(et, set()).add("<module>")

    return emit_sites, called, decorated


def _fully_wired_event_types() -> list[str]:
    """Live event types that have both a resolver and a template — the
    ones a member is entitled to actually receive."""
    out = []
    for et in registered_event_types():
        if not is_event_live(et):
            continue
        if get_resolver_for(et) is None:
            continue
        has_template = any(
            get_template_for(et, channel) is not None
            for channel in (CHANNEL_EMAIL_TRANSACTIONAL, CHANNEL_IN_APP)
        )
        if has_template:
            out.append(et)
    return out


class TestEmitSitesExist:
    """Layer 1 — the receiving half exists, so the sending half must."""

    def test_every_live_wired_event_has_an_emit_site(self, scan):
        emit_sites, _, _ = scan
        missing = [
            et for et in _fully_wired_event_types()
            if et not in emit_sites and et not in KNOWN_UNEMITTED
        ]
        assert not missing, (
            "These event types are live and have a resolver + template, "
            "but nothing in app/ emits them — a member would never "
            f"receive them: {missing}. Either wire an emit, or record "
            "the event in KNOWN_UNEMITTED with a reason."
        )

    def test_the_scan_actually_finds_emits(self, scan):
        """Self-check: a scan that silently found nothing would make
        every other assertion here vacuously true."""
        emit_sites, called, _ = scan
        assert len(emit_sites) > 20
        assert "gathering.booking.confirmed" in emit_sites
        assert len(called) > 100


class TestEmitSitesAreReachable:
    """Layer 2 — the emit is called, not merely written.

    This is the one that would have caught the booking-confirmation
    outage: the helper existed, contained the right event type, and was
    never invoked from anywhere.
    """

    def test_every_emit_site_is_called_or_is_a_route(self, scan):
        emit_sites, called, decorated = scan
        dead: dict[str, list[str]] = {}
        for et in _fully_wired_event_types():
            if et in KNOWN_UNEMITTED:
                continue
            fns = emit_sites.get(et, set())
            reachable = {
                fn for fn in fns
                if fn == "<module>" or fn in called or fn in decorated
            }
            if fns and not reachable and et not in KNOWN_UNREACHABLE:
                dead[et] = sorted(fns)
        assert not dead, (
            "These event types have an emit that nothing ever calls — "
            "the exact shape of the booking-confirmation outage, where a "
            "helper was written but never wired: "
            f"{dead}. Call it from the domain path, or record it in "
            "KNOWN_UNREACHABLE with a reason."
        )

    def test_booking_confirmation_emit_is_reachable(self, scan):
        """The specific regression, pinned by name so it cannot quietly
        come back."""
        emit_sites, called, decorated = scan
        fns = emit_sites.get("gathering.booking.confirmed", set())
        assert fns, "no emit site for gathering.booking.confirmed"
        assert any(fn in called or fn in decorated for fn in fns), (
            "gathering.booking.confirmed has an emit site that nothing "
            f"calls: {sorted(fns)}"
        )


class TestLegacyStandDownHasAReplacement:
    """Layer 2, targeted — every legacy trigger that stands down for a
    live topic must have a live comms replacement. This pairs the two
    halves of a cutover explicitly."""

    def test_stood_down_legacy_triggers_have_a_reachable_emit(self, scan):
        emit_sites, called, decorated = scan
        source = (
            APP_ROOT / "services" / "notification_service.py"
        ).read_text()
        tree = ast.parse(source)

        guarded: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name != "_rollout_is_live":
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    guarded.add(arg.value)

        assert guarded, "expected some legacy triggers to carry a guard"

        unreplaced = []
        for et in guarded:
            if not is_event_live(et):
                continue      # legacy still authoritative — fine
            fns = emit_sites.get(et, set())
            reachable = {
                fn for fn in fns
                if fn == "<module>" or fn in called or fn in decorated
            }
            if not reachable:
                unreplaced.append(et)

        assert not unreplaced, (
            "The legacy sender stands down for these live event types, "
            "but no reachable comms emit replaces it — nothing is being "
            f"sent at all: {unreplaced}"
        )
