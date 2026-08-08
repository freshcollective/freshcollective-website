"""RecipientResolver Protocol + registry.

One resolver per ``event_type``. Resolvers are pure functions of
``(session, event)`` returning a list of ``ResolvedRecipient`` —
they hit the domain models to determine who should potentially
receive a communication for this event and *why*, but do not
themselves check preferences, consent, or suppression. Those live
in the decision pipeline.

The ``human_reason`` field carried on each ResolvedRecipient is the
Refinement 3 transparency string that the member sees in their
communication history + email footers. Resolvers own it because
only the resolver knows the recipient's role (author / member /
mentioned / moderator / etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from sqlalchemy.orm import Session

from app.comms.models import CommunicationEvent


@dataclass(frozen=True)
class ResolvedRecipient:
    """One (user, role, why) tuple produced by a resolver.

    ``recipient_address_override`` is rare — most channels resolve
    the address from the user record (e.g. ``user.email``). Provide
    it only when the resolver has channel-specific address
    information the caller can't derive.

    ``template_context`` lets a resolver hand event-relevant data to
    the template renderer without the renderer having to reload it.
    Example: a comment_reply resolver can bundle the commenter's
    name here so the template doesn't need to re-query.
    """

    user_id: str
    role_in_event: str
    human_reason: str
    recipient_address_override: str | None = None
    template_context: dict[str, Any] = field(default_factory=dict)


class RecipientResolver(Protocol):
    """A resolver returns the list of recipients for one event_type.

    Implementations declare :attr:`event_type` — the dotted key the
    registry looks up. Registration is via :func:`register_resolver`
    or the ``@resolver_for`` decorator.
    """

    event_type: str

    def resolve(
        self,
        db: Session,
        event: CommunicationEvent,
    ) -> list[ResolvedRecipient]: ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_REGISTRY: dict[str, RecipientResolver] = {}


def register_resolver(resolver: RecipientResolver) -> None:
    """Register a resolver under its ``event_type``. Raises on duplicate."""
    if resolver.event_type in _REGISTRY:
        raise ValueError(
            f"RecipientResolver for {resolver.event_type!r} is already registered."
        )
    _REGISTRY[resolver.event_type] = resolver


def get_resolver_for(event_type: str) -> RecipientResolver | None:
    """Look up the resolver for an event_type, or None if unregistered."""
    return _REGISTRY.get(event_type)


def registered_event_types() -> tuple[str, ...]:
    """Diagnostic — every event_type that has a registered resolver."""
    return tuple(sorted(_REGISTRY.keys()))


def reset_registry() -> None:
    """Empty the registry. Intended for tests only."""
    _REGISTRY.clear()


def resolver_for(event_type: str) -> Callable[[type], type]:
    """Class decorator — registers the class after instantiation.

    Usage::

        @resolver_for("community.post.published")
        class NewPostResolver:
            event_type = "community.post.published"
            def resolve(self, db, event): ...
    """
    def _wrap(cls: type) -> type:
        instance = cls()
        setattr(instance, "event_type", event_type)  # belt-and-braces
        register_resolver(instance)  # type: ignore[arg-type]
        return cls
    return _wrap
