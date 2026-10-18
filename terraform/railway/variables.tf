# ---- where ------------------------------------------------------------------------------

variable "name_prefix" {
  description = "Name of the Railway project, and the prefix of the generated public subdomain."
  type        = string
  default     = "investigator"
}

variable "workspace_id" {
  description = "Railway workspace (team) id for the project. Empty: your personal workspace."
  type        = string
  default     = null
}

variable "region" {
  description = "Railway region for every service. asia-southeast1-eqsg3a (Singapore), us-west2, us-east4-eqdc4a, europe-west4-drams3a."
  type        = string
  default     = "asia-southeast1-eqsg3a"
}

variable "subdomain" {
  description = "Subdomain of the web service on up.railway.app. Empty: name_prefix plus a random suffix."
  type        = string
  default     = ""
}

variable "domain" {
  description = "Custom domain for the app (for example demo.example.com). Empty: use the up.railway.app address."
  type        = string
  default     = ""
}

variable "dns_resolver" {
  description = "Resolver nginx in the web image uses to find the API on Railway's private network (written as nginx expects an IPv6 address)."
  type        = string
  default     = "[fd12::10]"
}

# ---- images and sources -----------------------------------------------------------------

variable "image_owner" {
  description = "GitHub owner (lower case) whose GHCR packages hold investigator-api and investigator-web."
  type        = string
  default     = "anhnguyenk835"
}

variable "image_tag" {
  description = "Tag of the api and web images. A tag that moves (staging) is not redeployed by Railway on its own; use sha-xxxxxxx and apply, or redeploy from the dashboard."
  type        = string
  default     = "staging"
}

variable "ghcr_username" {
  description = "Only when the GHCR packages are private: GitHub user that may read them."
  type        = string
  default     = ""
}

variable "ghcr_token" {
  description = "Only when the GHCR packages are private: a personal access token with read:packages."
  type        = string
  default     = ""
  sensitive   = true
}

variable "github_repo" {
  description = "owner/name of the repository Railway builds the gateway from (infra/llm-gateway). Needs the Railway GitHub app installed on it."
  type        = string
  default     = "Anhnguyenk835/investigator-workspace"
}

variable "github_branch" {
  type    = string
  default = "main"
}

# ---- database ---------------------------------------------------------------------------

variable "expose_database" {
  description = "Open a public TCP proxy to Postgres, to load the demo data from your machine. Turn it off again afterwards."
  type        = bool
  default     = false
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
# Empty values are left unset. Add one later in the Railway dashboard (service -> Variables) or
# here, then apply.

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
