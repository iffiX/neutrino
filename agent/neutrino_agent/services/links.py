"""The links service: every published web service as a link that opens it.

There is nothing to toggle and no state to keep; the rows render straight
from the catalog's service offers.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations


class LinksService:
    """Renders the catalog's published web services as opening links."""

    def rows(self, *, catalog: dict) -> list:
        """The links the catalog's service offers name.

        Args:
            catalog: The catalog the hub last sent.

        Returns:
            One row per published web service: ``{"id", "title", "url"}``.
        """
        rows = []
        for offer_id, offer in sorted(catalog.get("services", {}).items()):
            if not isinstance(offer, dict) or offer.get("kind") != "link":
                continue
            rows.append(
                {
                    "id": offer_id,
                    "title": offer.get("title", offer_id),
                    "url": offer.get("url", ""),
                }
            )
        return rows
