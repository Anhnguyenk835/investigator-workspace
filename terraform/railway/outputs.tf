output "public_url" {
  description = "Where people open the app."
  value       = local.public_url
}

output "dns_records" {
  description = "Records to create at your registrar (custom domain only)."
  value = var.domain != "" ? [
    {
      type = "CNAME"
      name = railway_custom_domain.web[0].host_label != "" ? "${railway_custom_domain.web[0].host_label}.${railway_custom_domain.web[0].zone}" : var.domain
      data = railway_custom_domain.web[0].dns_record_value
    },
    {
      type = "TXT"
      name = "${railway_custom_domain.web[0].verification_host_label}.${railway_custom_domain.web[0].zone}"
      data = railway_custom_domain.web[0].verification_record_value
    },
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

output "database_proxy" {
  description = "host:port of the public Postgres proxy (expose_database = true), for loading the demo data."
  value       = var.expose_database ? "${railway_tcp_proxy.postgres[0].domain}:${railway_tcp_proxy.postgres[0].proxy_port}" : null
}

output "database_url_for_seeding" {
  description = "DATABASE_URL to use from your machine while expose_database = true."
  sensitive   = true
  value       = var.expose_database ? "postgresql://investigator:${random_password.db.result}@${railway_tcp_proxy.postgres[0].domain}:${railway_tcp_proxy.postgres[0].proxy_port}/investigator" : null
}

output "litellm_master_key" {
  description = "The gateway's key. Only needed to run the sample investigations from your machine."
  sensitive   = true
  value       = "sk-${random_password.litellm_master.result}"
}

output "guard_admin_token" {
  description = "Token for /admin/guardrails."
  sensitive   = true
  value       = random_password.admin.result
}
