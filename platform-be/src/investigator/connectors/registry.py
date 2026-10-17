from __future__ import annotations

import httpx

from investigator.connectors.base import SourceConnector
from investigator.connectors.confluence import ConfluenceConnector
from investigator.connectors.gmail import GmailConnector
from investigator.connectors.jira import JiraConnector
from investigator.connectors.notion import NotionConnector
from investigator.connectors.slack import SlackConnector
from investigator.demo import DemoConnector, DemoCorpus, RoutedConnector
from investigator.integrations import TokenProvider
from investigator.settings import Settings


def load_connectors(
    tokens: TokenProvider,
    http: httpx.AsyncClient,
    settings: Settings,
    demo: DemoCorpus | None = None,
) -> list[SourceConnector]:
    """Every source this deployment can read. A user who has not connected a source
    gets `not_connected` for it in the coverage report; nothing is invented."""
    live: list[SourceConnector] = [
        GmailConnector(tokens, http, label=settings.gmail_label),
        SlackConnector(tokens, http, channel_ids=settings.slack_channel_ids),
        JiraConnector(
            tokens,
            http,
            project_keys=settings.jira_project_keys,
            label=settings.jira_label,
            site_url=settings.atlassian_site_url,
        ),
        ConfluenceConnector(
            tokens,
            http,
            space_keys=settings.confluence_space_keys,
            site_url=settings.atlassian_site_url,
        ),
        NotionConnector(tokens, http),
    ]
    if demo is None:
        return live
    # Each source answers from the live API, or from the stored demo corpus for a demo visitor.
    return [RoutedConnector(c, DemoConnector(c.name, demo)) for c in live]
