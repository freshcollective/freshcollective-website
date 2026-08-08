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

# Importing the routing + templates packages registers every resolver
# and template at process start. The registrations are pure Python
# side effects — no DB reads or writes at import time.
from app.comms import routing  # noqa: F401 — registration
from app.comms import templates  # noqa: F401 — registration

# Register inbound webhook providers (Milestone 6). Same pattern as
# the outbound delivery provider bootstrap — the registry is populated
# at import so the receiver route can look up providers by key without
# an explicit init step.
from app.comms.webhooks import _bootstrap_webhook_providers as _bootstrap_wh
_bootstrap_wh()

__all__ = [
    "Channel",
    "Priority",
    "Source",
    "emit",
    "routing",
    "templates",
]
