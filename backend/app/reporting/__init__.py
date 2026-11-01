"""Shared reporting: metric registry, scoping and the admin API.

Importing this package registers the full metric catalogue. That is done
here rather than by each consumer because a partially loaded registry is
the kind of bug that shows up as a missing dashboard tile rather than as
an error — and because ``participation_rate`` divides by
``unique_members``, so the two families must both be present whichever
one a caller reached for first.

Order matters: the core metrics register before the engagement family
that depends on them, and World Builders last because it reads both the
creator journey's founder-operated definition and the participation
event union.
"""

from app.reporting import registry  # noqa: F401
from app.reporting import metrics  # noqa: F401 — registers the core family
from app.reporting import creators  # noqa: F401 — registers the creator journey
from app.reporting import belonging  # noqa: F401 — registers retention and overlap
from app.reporting import engagement  # noqa: F401 — registers participation
from app.reporting import world_builders  # noqa: F401 — the learning environment
