# ---- generated secrets ------------------------------------------------------------------

resource "random_id" "fernet" {
  byte_length = 32
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
  generated = {
    "database-url" = local.database_url
    # Fernet key: 32 random bytes, urlsafe base64 with padding.
    "token-encryption-key" = "${random_id.fernet.b64_url}="
    "litellm-master-key"   = "sk-${random_password.litellm_master.result}"
    "guard-alias-secret"   = random_password.alias.result
    "guard-admin-token"    = random_password.admin.result
  }

  # Secrets you may provide. A secret with an empty value is created empty and left unwired,
  # so the service still starts and the value can be added later.
  provided_values = {
    "gemini-api-key"          = var.gemini_api_key
    "openai-api-key"          = var.openai_api_key
    "anthropic-api-key"       = var.anthropic_api_key
    "google-client-secret"    = var.google_client_secret
    "slack-client-secret"     = var.slack_client_secret
    "atlassian-client-secret" = var.atlassian_client_secret
    "notion-client-secret"    = var.notion_client_secret
  }
  # Only whether a value is set is used to decide what to create, so the values stay sensitive.
  provided = { for k, v in local.provided_values : k => true if nonsensitive(v != "") }

  secret_names = toset(concat(keys(local.generated), keys(local.provided_values)))
}

resource "google_secret_manager_secret" "s" {
  for_each  = local.secret_names
  secret_id = "${var.name_prefix}-${each.value}"

  replication {
    auto {}
  }

  depends_on = [google_project_service.api]
}

resource "google_secret_manager_secret_version" "generated" {
  for_each    = local.generated
  secret      = google_secret_manager_secret.s[each.key].id
  secret_data = each.value
}

resource "google_secret_manager_secret_version" "provided" {
  for_each    = local.provided
  secret      = google_secret_manager_secret.s[each.key].id
  secret_data = local.provided_values[each.key]
}

# The gateway's routes, mounted as a file. Not secret, but Cloud Run cannot mount a repo file.
resource "google_secret_manager_secret" "litellm_config" {
  secret_id = "${var.name_prefix}-litellm-config"
  replication {
    auto {}
  }
  depends_on = [google_project_service.api]
}

resource "google_secret_manager_secret_version" "litellm_config" {
  secret      = google_secret_manager_secret.litellm_config.id
  secret_data = file("${path.module}/../infra/llm-gateway/config.yaml")
}

locals {
  # Which secret each service reads. Provided secrets count only when they have a value.
  api_secret_names = concat(
    ["database-url", "token-encryption-key", "litellm-master-key", "guard-alias-secret", "guard-admin-token"],
    [for k in ["google-client-secret", "slack-client-secret", "atlassian-client-secret", "notion-client-secret"] : k if contains(keys(local.provided), k)],
  )
  litellm_secret_names = concat(
    ["litellm-master-key"],
    [for k in ["gemini-api-key", "openai-api-key", "anthropic-api-key"] : k if contains(keys(local.provided), k)],
  )
}
