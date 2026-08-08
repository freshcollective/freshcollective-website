"""Communications routing engine — Milestone 5b.

The routing layer answers "given a CommunicationEvent, what intents
should exist?" It sits between the event log (M1) and the intent /
delivery model (M4). Every decision — recipient resolution,
preference / consent / suppression checks, priority assignment,
rate-limit downgrade, quiet-hours reschedule, provider selection,
template rendering, intent creation — happens here.

Shadow-only in M5b
------------------

The public :func:`route_event` accepts a ``delivery_mode`` argument.
No production code path calls it yet — that arrives with the M5c
emit-site wiring plus the ``COMMS_SHADOW`` / ``COMMS_LIVE_TOPICS``
config surfaces. Tests exercise both modes to verify the pipeline
is complete; the production runtime remains fully driven by the
legacy communication code paths.

Package layout
--------------

  * ``resolver.py``       — RecipientResolver Protocol + registry
  * ``provider_map.py``   — (category, channel) → provider_key
  * ``pacing.py``         — priority resolution, rate-limit, quiet hours
  * ``decision.py``       — the per-recipient-per-channel pipeline
  * ``routing.py``        — top-level ``route_event`` orchestration
  * ``resolvers/``        — one submodule per event area, each
                             registering resolvers on import
"""

from __future__ import annotations

from app.comms.routing.provider_map import (
    PROVIDER_MAP,
    get_provider_for,
    supported_channels_for_category,
)
from app.comms.routing.resolver import (
    RecipientResolver,
    ResolvedRecipient,
    get_resolver_for,
    register_resolver,
)
from app.comms.routing.routing import RoutingResult, route_event


# Registering resolvers is a side-effect of importing each submodule.
# The templates package is registered analogously — see
# ``app.comms.templates``.
from app.comms.routing import resolvers  # noqa: F401 — registration


__all__ = [
    "PROVIDER_MAP",
    "RecipientResolver",
    "ResolvedRecipient",
    "RoutingResult",
    "get_provider_for",
    "get_resolver_for",
    "register_resolver",
    "route_event",
    "supported_channels_for_category",
]
