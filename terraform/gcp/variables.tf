# ---- where ------------------------------------------------------------------------------

variable "project_id" {
  description = "GCP project that hosts the demo."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Cloud SQL and Artifact Registry. Cloud Run domain mappings are not offered in every region; see README."
  type        = string
  default     = "asia-southeast1"
}

variable "name_prefix" {
  description = "Prefix of every resource name."
  type        = string
  default     = "investigator"
}

variable "github_repo" {
  description = "owner/name of the repository whose Actions may deploy."
  type        = string
  default     = "Anhnguyenk835/investigator-workspace"
}

variable "domain" {
  description = "Custom domain for the app (for example demo.example.com). Empty: use the run.app address of the web service."
  type        = string
  default     = ""
}

variable "enable_domain_mapping" {
  description = "Create the Cloud Run domain mapping for `domain`. Turn off in a region without domain mappings and put a load balancer in front instead."
  type        = bool
  default     = true
}

# ---- cost switches ----------------------------------------------------------------------

variable "demo_running" {
  description = "false stops the demo: the API and gateway scale to zero and Cloud SQL is stopped (storage is kept). true starts it again."
  type        = bool
  default     = true
}

variable "litellm_always_on" {
  description = "Keep one gateway instance warm. Off saves money; the first model call after idle takes 10 to 20 s longer."
  type        = bool
  default     = false
}

# ---- sizing -----------------------------------------------------------------------------

variable "sql_tier" {
  description = "Cloud SQL machine type. db-g1-small if the shared-core tier stalls."
  type        = string
  default     = "db-f1-micro"
}

variable "sql_disk_gb" {
  type    = number
  default = 10
}

variable "sql_deletion_protection" {
  description = "Refuse to destroy the database. Off for a demo so `terraform destroy` works."
  type        = bool
  default     = false
}

variable "api_cpu" {
  type    = string
  default = "1"
}

variable "api_memory" {
  type    = string
  default = "1Gi"
}

# ---- demo behaviour ---------------------------------------------------------------------

variable "demo_day_cost_usd" {
  description = "Real LLM spend the demo may use per day, across all visitors."
  type        = number
  default     = 5
}

variable "demo_max_investigations" {
  type    = number
  default = 5
}

variable "demo_max_chat_turns" {
  type    = number
  default = 40
}

variable "demo_sessions_per_ip_hour" {
  type    = number
  default = 5
}

variable "auth_allowed_domains" {
  description = "Comma separated email domains allowed to sign in. Empty: any verified Google account."
  type        = string
  default     = ""
}

variable "auth_allowed_emails" {
  description = "Comma separated emails allowed to sign in."
  type        = string
  default     = ""
}

# ---- OAuth apps (ids are not secret) ----------------------------------------------------

variable "google_client_id" {
  type    = string
  default = ""
}

variable "slack_client_id" {
  type    = string
  default = ""
}

variable "atlassian_client_id" {
  type    = string
  default = ""
}

variable "notion_client_id" {
  type    = string
  default = ""
}

# ---- secrets you provide ----------------------------------------------------------------
# Leave a value empty and add it later instead:
#   printf '%s' "$KEY" | gcloud secrets versions add investigator-gemini-api-key --data-file=-
# then redeploy the service so it reads the new version.

variable "gemini_api_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "openai_api_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "anthropic_api_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "google_client_secret" {
  type      = string
  default   = ""
  sensitive = true
}

variable "slack_client_secret" {
  type      = string
  default   = ""
  sensitive = true
}

variable "atlassian_client_secret" {
  type      = string
  default   = ""
  sensitive = true
}

variable "notion_client_secret" {
  type      = string
  default   = ""
  sensitive = true
}

# ---- monitoring (optional) --------------------------------------------------------------

variable "alert_email" {
  description = "Email for budget alerts and the uptime check. Empty: no alerts."
  type        = string
  default     = ""
}

variable "billing_account" {
  description = "Billing account id (XXXXXX-XXXXXX-XXXXXX) for the budget. Empty: no budget."
  type        = string
  default     = ""
}

variable "budget_usd" {
  type    = number
  default = 100
}
