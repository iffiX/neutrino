"""The web service type: a published link the page opens.

There is nothing to toggle and no state to keep; the rows render straight
from the typed entries, and the browser itself is what opens the payload's
url.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

from neutrino_agent.services.base import ServiceTypeHandler


class WebServiceHandler(ServiceTypeHandler):
    """The web type has no machine-side actions or state."""

    service_type = "web"
