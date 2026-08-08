"""Template registry — (event_type, channel) → Template."""

from __future__ import annotations

from typing import Callable

from app.comms.templates.base import Template


_REGISTRY: dict[tuple[str, str], Template] = {}


def register_template(template: Template) -> None:
    """Register a template under ``(event_type, channel)``. Raises on duplicate."""
    key = (template.event_type, template.channel)
    if key in _REGISTRY:
        raise ValueError(
            f"Template for {template.event_type!r} × {template.channel!r} "
            f"is already registered."
        )
    _REGISTRY[key] = template


def get_template_for(event_type: str, channel: str) -> Template | None:
    """Look up a template; None when unregistered.

    The decision pipeline treats ``None`` as a signal to skip that
    (recipient × channel) pair without creating an intent — an event
    with no template for a channel simply isn't communicated on that
    channel yet.
    """
    return _REGISTRY.get((event_type, channel))


def registered_templates() -> tuple[tuple[str, str], ...]:
    """Diagnostic — every (event_type, channel) pair registered."""
    return tuple(sorted(_REGISTRY.keys()))


def reset_registry() -> None:
    """Empty the registry. Intended for tests only."""
    _REGISTRY.clear()


def template_for(event_type: str, channel: str) -> Callable[[type], type]:
    """Class decorator — instantiates the class and registers the
    instance. The wrapped class must define ``key`` and ``version``;
    ``event_type`` and ``channel`` are stamped from the decorator args
    for consistency.
    """
    def _wrap(cls: type) -> type:
        instance = cls()
        setattr(instance, "event_type", event_type)
        setattr(instance, "channel", channel)
        register_template(instance)  # type: ignore[arg-type]
        return cls
    return _wrap
