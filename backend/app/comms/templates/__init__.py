"""Communications templates — M5b renderers.

Templates turn ``(event, recipient)`` into a :class:`RenderedPayload`.
One template per ``(event_type, channel)`` pair; registered at import
time in each submodule. The decision pipeline calls
:func:`get_template_for` after preference / consent / suppression
checks pass.

Copy tone
---------

Every template follows the Atlas language substitutions and the
Communications Principles — no urgency, no metrics, warm and
concrete. The rendered ``human_reason`` (Refinement 3) is carried
on the intent itself; templates should not duplicate it in the
body.
"""

from __future__ import annotations

from app.comms.templates.base import Template
from app.comms.templates.registry import (
    get_template_for,
    register_template,
    registered_templates,
    reset_registry,
    template_for,
)


# Concrete template modules — imports register them.
from app.comms.templates import account         # noqa: F401
from app.comms.templates import community       # noqa: F401
from app.comms.templates import gatherings      # noqa: F401
from app.comms.templates import messages        # noqa: F401
from app.comms.templates import pathways        # noqa: F401


__all__ = [
    "Template",
    "get_template_for",
    "register_template",
    "registered_templates",
    "reset_registry",
    "template_for",
]
