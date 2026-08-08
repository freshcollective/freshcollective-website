"""Template Protocol + shared render helpers."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session

from app.comms.models import CommunicationEvent
from app.comms.providers.base import RenderedPayload
from app.comms.routing.resolver import ResolvedRecipient


class Template(Protocol):
    """Renders a (event, recipient) pair to a :class:`RenderedPayload`
    ready to hand to a provider.

    Implementations declare :attr:`key` (unique per registry — the
    natural key is ``{event_type}.{channel}``), :attr:`version` (a
    semver-ish string bumped when subject/body semantics change), and
    :attr:`channel` (the channel this template renders for).
    """

    key: str
    version: str
    event_type: str
    channel: str

    def render(
        self,
        db: Session,
        event: CommunicationEvent,
        recipient: ResolvedRecipient,
    ) -> RenderedPayload: ...


__all__ = ["RenderedPayload", "Template"]
