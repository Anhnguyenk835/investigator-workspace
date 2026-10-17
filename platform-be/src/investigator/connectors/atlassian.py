"""Finding the user's Atlassian cloud site, shared by Jira and Confluence."""

from __future__ import annotations

from investigator.connectors.support import SourceDenied
from investigator.integrations import TokenProvider
from investigator.tools import AccessContext


async def cloud_site(
    tokens: TokenProvider, ctx: AccessContext, wanted_url: str, product: str
) -> tuple[str, str]:
    """(cloud id, human site URL). Prefers the configured site, else the first one."""
    sites = (await tokens.account(ctx.user_id, "atlassian")).get("sites") or []
    if not sites:
        raise SourceDenied("No Atlassian site is accessible with this account.")
    wanted = wanted_url.rstrip("/")
    site = next(
        (s for s in sites if wanted and (s.get("url") or "").rstrip("/") == wanted),
        sites[0],
    )
    return str(site["id"]), str(site.get("url") or "").rstrip("/")
