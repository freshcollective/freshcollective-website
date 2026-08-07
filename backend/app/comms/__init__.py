"""Fresh Collective Communications Layer.

Milestone 1: event log + topic/category registry + emit().

Public API:

    from app.comms import emit
    from app.comms.categories import Source, Priority, Channel

Domain code calls ``emit()`` when a communication-worthy event happens.
Delivery is not attempted in Milestone 1 — events are recorded for
future routing, decision, and delivery layers (Milestones 4+).

See ``docs/communications-architecture.md`` for the full design.
"""

# Import models so SQLAlchemy registers them on Base.metadata whenever
# any part of the comms package is imported.
from app.comms import models  # noqa: F401

from app.comms.categories import Channel, Priority, Source
from app.comms.events import emit

__all__ = [
    "Channel",
    "Priority",
    "Source",
    "emit",
]
