output "public_url" {
  description = "Where people open the app."
  value       = local.public_url
}

output "service_urls" {
  value = {
    web     = local.web_url
    api     = local.api_url
    litellm = local.litellm_url
  }
}

output "dns_records" {
  description = "Records to create at your registrar (domain mapping only)."
  value = local.map_domain ? [
    for r in google_cloud_run_domain_mapping.web[0].status[0].resource_records : {
      type = r.type
      name = r.name == "" ? var.domain : r.name
      data = r.rrdata
    }
  ] : []
}

output "redirect_uris" {
  description = "Register these with each provider."
  value = {
    google_sign_in = "${local.public_url}/api/auth/google/callback"
    gmail          = "${local.public_url}/api/integrations/google/callback"
    slack          = "${local.public_url}/api/integrations/slack/callback"
    atlassian      = "${local.public_url}/api/integrations/atlassian/callback"
    notion         = "${local.public_url}/api/integrations/notion/callback"
  }
}

output "github_variables" {
  description = "Repository variables for the deploy job: GCP_PROJECT_ID, GCP_REGION, GCP_WORKLOAD_IDENTITY_PROVIDER, GCP_DEPLOYER_SERVICE_ACCOUNT, GCP_NAME_PREFIX."
  value = {
    GCP_PROJECT_ID                 = local.project
    GCP_REGION                     = local.region
    GCP_NAME_PREFIX                = var.name_prefix
    GCP_WORKLOAD_IDENTITY_PROVIDER = google_iam_workload_identity_pool_provider.github.name
    GCP_DEPLOYER_SERVICE_ACCOUNT   = google_service_account.deployer.email
  }
}

output "image_repository" {
  description = "Where CI pushes the api and web images."
  value       = "${local.registry}/${google_artifact_registry_repository.images.repository_id}"
}

output "sql_connection_name" {
  value = google_sql_database_instance.main.connection_name
}

output "sql_proxy_command" {
  description = "Reach the database from your machine, for loading the demo data."
  value       = "cloud-sql-proxy ${google_sql_database_instance.main.connection_name} --port 5443"
}

output "guard_admin_token_secret" {
  description = "Secret that holds the /admin/guardrails token."
  value       = google_secret_manager_secret.s["guard-admin-token"].secret_id
}
