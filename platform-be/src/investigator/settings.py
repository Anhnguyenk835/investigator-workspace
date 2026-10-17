from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

GuardMode = Literal["off", "monitor", "enforce"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    litellm_base_url: str = "http://127.0.0.1:4000"
    litellm_api_key: str = ""
    cors_origins: list[str] = ["http://localhost:5173"]
    database_url: str = (
        "postgresql://investigator:investigator@127.0.0.1:5442/investigator"
    )

    # Investigation runs are queued in Postgres and taken by workers. The API process runs
    # this many itself; set 0 and start `python -m investigator.worker` separately to scale out.
    embedded_workers: int = 2
    job_lease_seconds: float = 60.0

    # OAuth integrations. Each provider is off until both its id and secret are set.
    # Fernet key that encrypts stored tokens; without it no provider can connect.
    token_encryption_key: str = ""
    # Public base URL of this API; providers redirect back to it.
    api_public_url: str = "http://127.0.0.1:8010"
    # Where the browser lands after a connect attempt (the web app).
    oauth_return_url: str = "http://localhost:5173/settings/connectors"
    # What each source may read. Empty means everything the signed-in user can read.
    gmail_label: str = ""
    slack_channel_ids: str = ""
    jira_project_keys: str = ""
    jira_label: str = ""
    confluence_space_keys: str = ""
    atlassian_site_url: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    slack_client_id: str = ""
    slack_client_secret: str = ""
    atlassian_client_id: str = ""
    atlassian_client_secret: str = ""
    notion_client_id: str = ""
    notion_client_secret: str = ""

    # LLM guardrails. Each guard is off, monitor (records what it would do) or enforce.
    guard_enabled: bool = True
    guard_secrets_mode: GuardMode = "enforce"
    guard_pii_mode: GuardMode = "monitor"
    guard_injection_mode: GuardMode = "monitor"
    guard_output_mode: GuardMode = "monitor"
    guard_egress_mode: GuardMode = "monitor"
    guard_budget_mode: GuardMode = "monitor"
    guard_breaker_mode: GuardMode = "monitor"
    guard_audit_fail_closed: bool = False
    # Stops every model call when true; for a running system use the admin kill endpoint.
    guard_kill_switch: bool = False
    # Shared secret for /admin/guardrails. Unset leaves the admin API off.
    guard_admin_token: str = ""
    guard_breaker_threshold: int = 5
    # Keys the hashes that number placeholders. Set it to share numbering across processes.
    guard_alias_secret: str = ""
    # A JSON file of policy values (modes, limits, allowed link hosts). Settings set in the
    # environment override it.
    guard_policy_file: str = ""

    # Sign-in. With it off every request is one local user (tests, quick local use).
    auth_enabled: bool = True
    # Where the web app is served from; the sign-in callback and the origin check use it.
    web_public_url: str = "http://localhost:5173"
    # Sign-in goes through the web origin's /api proxy so the session cookie is first-party.
    auth_redirect_uri: str = ""
    # Empty means any verified Google account may sign in.
    auth_allowed_domains: str = ""
    auth_allowed_emails: str = ""
    auth_session_days: int = 14
    auth_cookie_secure: bool = False
    # The no-login demo over stored fictional data.
    demo_enabled: bool = True
    demo_session_hours: int = 24
    demo_sessions_per_ip_hour: int = 5
    demo_max_investigations: int = 5
    demo_max_chat_turns: int = 40
    demo_day_cost_usd: float = 10.0
    guard_run_max_cost_usd: float = 6.0
    guard_ip_day_max_cost_usd: float = 40.0
    guard_global_day_max_cost_usd: float = 200.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
