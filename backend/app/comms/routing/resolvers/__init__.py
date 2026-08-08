"""Concrete resolvers.

Importing this package registers every resolver on the routing
registry via each submodule's decorator side effects.
"""

# noqa: F401 imports — side-effect registration only.
from app.comms.routing.resolvers import account       # noqa: F401
from app.comms.routing.resolvers import community     # noqa: F401
from app.comms.routing.resolvers import gatherings    # noqa: F401
from app.comms.routing.resolvers import messages      # noqa: F401
from app.comms.routing.resolvers import pathways      # noqa: F401
