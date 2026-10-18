# Every service starts from Google's placeholder image so `terraform apply` works before any
# image exists. CI then deploys the real image, and Terraform ignores the image from then on.

locals {
  # Secret-backed environment variables of the API: ENV_NAME => secret name.
  api_secret_env = merge(
    {
      DATABASE_URL         = "database-url"
      TOKEN_ENCRYPTION_KEY = "token-encryption-key"
      LITELLM_API_KEY      = "litellm-master-key"
      GUARD_ALIAS_SECRET   = "guard-alias-secret"
      GUARD_ADMIN_TOKEN    = "guard-admin-token"
    },
    contains(keys(local.provided), "google-client-secret") ? { GOOGLE_CLIENT_SECRET = "google-client-secret" } : {},
    contains(keys(local.provided), "slack-client-secret") ? { SLACK_CLIENT_SECRET = "slack-client-secret" } : {},
    contains(keys(local.provided), "atlassian-client-secret") ? { ATLASSIAN_CLIENT_SECRET = "atlassian-client-secret" } : {},
    contains(keys(local.provided), "notion-client-secret") ? { NOTION_CLIENT_SECRET = "notion-client-secret" } : {},
  )

  api_env = {
    AUTH_ENABLED              = "true"
    AUTH_COOKIE_SECURE        = "true"
    AUTH_ALLOWED_DOMAINS      = var.auth_allowed_domains
    AUTH_ALLOWED_EMAILS       = var.auth_allowed_emails
    WEB_PUBLIC_URL            = local.public_url
    API_PUBLIC_URL            = "${local.public_url}/api"
    OAUTH_RETURN_URL          = "${local.public_url}/settings/connectors"
    CORS_ORIGINS              = jsonencode([local.public_url])
    LITELLM_BASE_URL          = local.litellm_url
    EMBEDDED_WORKERS          = "2"
    DEMO_ENABLED              = "true"
    DEMO_DAY_COST_USD         = tostring(var.demo_day_cost_usd)
    DEMO_MAX_INVESTIGATIONS   = tostring(var.demo_max_investigations)
    DEMO_MAX_CHAT_TURNS       = tostring(var.demo_max_chat_turns)
    DEMO_SESSIONS_PER_IP_HOUR = tostring(var.demo_sessions_per_ip_hour)
    GOOGLE_CLIENT_ID          = var.google_client_id
    SLACK_CLIENT_ID           = var.slack_client_id
    ATLASSIAN_CLIENT_ID       = var.atlassian_client_id
    NOTION_CLIENT_ID          = var.notion_client_id
  }

  litellm_secret_env = merge(
    { LITELLM_MASTER_KEY = "litellm-master-key" },
    contains(keys(local.provided), "gemini-api-key") ? { GEMINI_API_KEY = "gemini-api-key" } : {},
    contains(keys(local.provided), "openai-api-key") ? { OPENAI_API_KEY = "openai-api-key" } : {},
    contains(keys(local.provided), "anthropic-api-key") ? { ANTHROPIC_API_KEY = "anthropic-api-key" } : {},
  )
}

# ---- api --------------------------------------------------------------------------------
# One instance with CPU always allocated: investigation workers and the idle-session sweep run
# inside the process, and chat and progress streams stay open for minutes.

resource "google_cloud_run_v2_service" "api" {
  name                = "${var.name_prefix}-api"
  location            = local.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.api.email
    timeout         = "3600s"

    scaling {
      min_instance_count = var.demo_running ? 1 : 0
      max_instance_count = 1
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }

    containers {
      image = local.placeholder_image

      ports {
        container_port = 8010
      }

      resources {
        limits = {
          cpu    = var.api_cpu
          memory = var.api_memory
        }
        cpu_idle          = false # CPU stays allocated between requests
        startup_cpu_boost = true
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      dynamic "env" {
        for_each = local.api_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.api_secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.s[env.value].secret_id
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        tcp_socket {
          port = 8010
        }
        period_seconds    = 5
        timeout_seconds   = 3
        failure_threshold = 24
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [
    google_secret_manager_secret_iam_member.api,
    google_secret_manager_secret_version.generated,
    google_secret_manager_secret_version.provided,
    google_project_iam_member.api_sql,
    google_sql_database.app,
    google_sql_user.app,
  ]
}

# ---- web --------------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "web" {
  name                = "${var.name_prefix}-web"
  location            = local.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.web.email
    timeout         = "3600s"

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = local.placeholder_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "256Mi"
        }
        cpu_idle = true
      }

      env {
        name  = "API_UPSTREAM"
        value = local.api_url
      }
      env {
        name  = "DNS_RESOLVER"
        value = "8.8.8.8"
      }

      startup_probe {
        tcp_socket {
          port = 8080
        }
        period_seconds    = 3
        timeout_seconds   = 2
        failure_threshold = 10
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [google_project_service.api]
}

# ---- litellm ----------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "litellm" {
  name                = "${var.name_prefix}-litellm"
  location            = local.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.litellm.email
    timeout         = "600s"

    scaling {
      min_instance_count = var.demo_running && var.litellm_always_on ? 1 : 0
      max_instance_count = 2
    }

    volumes {
      name = "config"
      secret {
        secret = google_secret_manager_secret.litellm_config.secret_id
        items {
          version = "latest"
          path    = "config.yaml"
        }
      }
    }

    containers {
      image = local.litellm_image
      args  = ["--config", "/app/config/config.yaml", "--host", "0.0.0.0", "--port", "4000", "--telemetry", "False"]

      ports {
        container_port = 4000
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      volume_mounts {
        name       = "config"
        mount_path = "/app/config"
      }

      env {
        name  = "STORE_MODEL_IN_DB"
        value = "False"
      }

      dynamic "env" {
        for_each = local.litellm_secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.s[env.value].secret_id
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        tcp_socket {
          port = 4000
        }
        period_seconds    = 5
        timeout_seconds   = 3
        failure_threshold = 36
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.litellm,
    google_secret_manager_secret_iam_member.litellm_config,
    google_secret_manager_secret_version.generated,
    google_secret_manager_secret_version.provided,
    google_secret_manager_secret_version.litellm_config,
  ]
}

# The services are reachable from the internet. The API does its own sign-in; the gateway
# requires its master key on every request.
resource "google_cloud_run_v2_service_iam_member" "public" {
  for_each = {
    api     = google_cloud_run_v2_service.api.name
    web     = google_cloud_run_v2_service.web.name
    litellm = google_cloud_run_v2_service.litellm.name
  }
  project  = local.project
  location = local.region
  name     = each.value
  role     = "roles/run.invoker"
  member   = "allUsers"
}
