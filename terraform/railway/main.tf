# Four services in one Railway project: postgres, litellm (the model gateway), api and web.
# They talk over Railway's private network (<service>.railway.internal); only web is public.

resource "random_id" "subdomain" {
  byte_length = 2
}

resource "random_id" "fernet" {
  byte_length = 32
}

resource "random_password" "db" {
  length  = 32
  special = false # goes into a URL
}

resource "random_password" "litellm_master" {
  length  = 40
  special = false
}

resource "random_password" "alias" {
  length  = 40
  special = false
}

resource "random_password" "admin" {
  length  = 40
  special = false
}

locals {
  env_id = railway_project.main.default_environment.id

  subdomain  = var.subdomain != "" ? var.subdomain : "${var.name_prefix}-${random_id.subdomain.hex}"
  public_url = var.domain != "" ? "https://${var.domain}" : "https://${railway_service_domain.web.domain}"

  api_port     = 8010
  web_port     = 8080
  litellm_port = 4000

  litellm_url  = "http://litellm.railway.internal:${local.litellm_port}"
  api_url      = "http://api.railway.internal:${local.api_port}"
  database_url = "postgresql://investigator:${random_password.db.result}@postgres.railway.internal:5432/investigator"

  regions = [{ region = var.region, num_replicas = 1 }]

  registry_user = var.ghcr_username != "" ? var.ghcr_username : null
  registry_pass = nonsensitive(var.ghcr_token != "") ? var.ghcr_token : null

  postgres_env = {
    POSTGRES_USER     = "investigator"
    POSTGRES_PASSWORD = random_password.db.result
    POSTGRES_DB       = "investigator"
    # Railway mounts the volume with a lost+found directory; Postgres needs an empty one.
    PGDATA = "/var/lib/postgresql/data/pgdata"
  }

  litellm_env = merge(
    {
      PORT               = tostring(local.litellm_port)
      LITELLM_MASTER_KEY = "sk-${random_password.litellm_master.result}"
      STORE_MODEL_IN_DB  = "False"
    },
    nonsensitive(var.gemini_api_key != "") ? { GEMINI_API_KEY = var.gemini_api_key } : {},
    nonsensitive(var.openai_api_key != "") ? { OPENAI_API_KEY = var.openai_api_key } : {},
    nonsensitive(var.anthropic_api_key != "") ? { ANTHROPIC_API_KEY = var.anthropic_api_key } : {},
  )

  api_env = merge(
    {
      PORT                      = tostring(local.api_port)
      DATABASE_URL              = local.database_url
      TOKEN_ENCRYPTION_KEY      = "${random_id.fernet.b64_url}="
      LITELLM_API_KEY           = "sk-${random_password.litellm_master.result}"
      LITELLM_BASE_URL          = local.litellm_url
      GUARD_ALIAS_SECRET        = random_password.alias.result
      GUARD_ADMIN_TOKEN         = random_password.admin.result
      AUTH_ENABLED              = "true"
      AUTH_COOKIE_SECURE        = "true"
      WEB_PUBLIC_URL            = local.public_url
      API_PUBLIC_URL            = "${local.public_url}/api"
      OAUTH_RETURN_URL          = "${local.public_url}/settings/connectors"
      CORS_ORIGINS              = jsonencode([local.public_url])
      EMBEDDED_WORKERS          = "2"
      DEMO_ENABLED              = "true"
      DEMO_DAY_COST_USD         = tostring(var.demo_day_cost_usd)
      DEMO_MAX_INVESTIGATIONS   = tostring(var.demo_max_investigations)
      DEMO_MAX_CHAT_TURNS       = tostring(var.demo_max_chat_turns)
      DEMO_SESSIONS_PER_IP_HOUR = tostring(var.demo_sessions_per_ip_hour)
    },
    var.auth_allowed_domains != "" ? { AUTH_ALLOWED_DOMAINS = var.auth_allowed_domains } : {},
    var.auth_allowed_emails != "" ? { AUTH_ALLOWED_EMAILS = var.auth_allowed_emails } : {},
    var.google_client_id != "" ? { GOOGLE_CLIENT_ID = var.google_client_id } : {},
    var.slack_client_id != "" ? { SLACK_CLIENT_ID = var.slack_client_id } : {},
    var.atlassian_client_id != "" ? { ATLASSIAN_CLIENT_ID = var.atlassian_client_id } : {},
    var.notion_client_id != "" ? { NOTION_CLIENT_ID = var.notion_client_id } : {},
    nonsensitive(var.google_client_secret != "") ? { GOOGLE_CLIENT_SECRET = var.google_client_secret } : {},
    nonsensitive(var.slack_client_secret != "") ? { SLACK_CLIENT_SECRET = var.slack_client_secret } : {},
    nonsensitive(var.atlassian_client_secret != "") ? { ATLASSIAN_CLIENT_SECRET = var.atlassian_client_secret } : {},
    nonsensitive(var.notion_client_secret != "") ? { NOTION_CLIENT_SECRET = var.notion_client_secret } : {},
  )

  web_env = {
    PORT         = tostring(local.web_port)
    API_UPSTREAM = local.api_url
    DNS_RESOLVER = var.dns_resolver
  }
}

resource "railway_project" "main" {
  name         = var.name_prefix
  description  = "The Investigator demo"
  workspace_id = var.workspace_id
}

# ---- postgres ---------------------------------------------------------------------------

resource "railway_service" "postgres" {
  name         = "postgres"
  project_id   = railway_project.main.id
  source_image = "postgres:17-alpine"
  regions      = local.regions

  volume = {
    name       = "postgres-data"
    mount_path = "/var/lib/postgresql/data"
  }
}

resource "railway_variable_collection" "postgres" {
  environment_id = local.env_id
  service_id     = railway_service.postgres.id
  variables      = [for k, v in local.postgres_env : { name = k, value = v }]
}

# Only to load the demo data from your machine; see README.
resource "railway_tcp_proxy" "postgres" {
  count            = var.expose_database ? 1 : 0
  environment_id   = local.env_id
  service_id       = railway_service.postgres.id
  application_port = 5432
}

# ---- litellm ----------------------------------------------------------------------------
# Built by Railway from infra/llm-gateway/Dockerfile (the routes are baked into the image).

resource "railway_service" "litellm" {
  name               = "litellm"
  project_id         = railway_project.main.id
  source_repo        = var.github_repo
  source_repo_branch = var.github_branch
  root_directory     = "infra/llm-gateway"
  regions            = local.regions
}

resource "railway_variable_collection" "litellm" {
  environment_id = local.env_id
  service_id     = railway_service.litellm.id
  variables      = [for k, v in local.litellm_env : { name = k, value = v }]
}

# ---- api --------------------------------------------------------------------------------
# Exactly one replica: investigation workers and the idle-session sweep run inside the process.

resource "railway_service" "api" {
  name                           = "api"
  project_id                     = railway_project.main.id
  source_image                   = "ghcr.io/${var.image_owner}/investigator-api:${var.image_tag}"
  source_image_registry_username = local.registry_user
  source_image_registry_password = local.registry_pass
  regions                        = local.regions
}

resource "railway_variable_collection" "api" {
  environment_id = local.env_id
  service_id     = railway_service.api.id
  variables      = [for k, v in local.api_env : { name = k, value = v }]

  depends_on = [railway_variable_collection.postgres, railway_variable_collection.litellm]
}

# ---- web --------------------------------------------------------------------------------

resource "railway_service" "web" {
  name                           = "web"
  project_id                     = railway_project.main.id
  source_image                   = "ghcr.io/${var.image_owner}/investigator-web:${var.image_tag}"
  source_image_registry_username = local.registry_user
  source_image_registry_password = local.registry_pass
  regions                        = local.regions
}

resource "railway_variable_collection" "web" {
  environment_id = local.env_id
  service_id     = railway_service.web.id
  variables      = [for k, v in local.web_env : { name = k, value = v }]
}

resource "railway_service_domain" "web" {
  environment_id = local.env_id
  service_id     = railway_service.web.id
  subdomain      = local.subdomain
}

# Needs two DNS records at your registrar; see the dns_records output.
resource "railway_custom_domain" "web" {
  count          = var.domain != "" ? 1 : 0
  environment_id = local.env_id
  service_id     = railway_service.web.id
  domain         = var.domain
  target_port    = local.web_port
}
