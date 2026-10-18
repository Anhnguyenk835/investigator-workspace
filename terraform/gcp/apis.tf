locals {
  apis = [
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "monitoring.googleapis.com",
    "billingbudgets.googleapis.com",
    "gmail.googleapis.com", # the Gmail connection reads mail with the user's own OAuth grant
  ]
}

resource "google_project_service" "api" {
  for_each           = toset(local.apis)
  service            = each.value
  disable_on_destroy = false
}

data "google_project" "this" {
  project_id = var.project_id
}

locals {
  region  = var.region
  project = var.project_id
  number  = data.google_project.this.number

  # Cloud Run addresses follow a fixed pattern, so the services can name each other without
  # waiting for the other to exist.
  web_url     = "https://${var.name_prefix}-web-${local.number}.${local.region}.run.app"
  api_url     = "https://${var.name_prefix}-api-${local.number}.${local.region}.run.app"
  litellm_url = "https://${var.name_prefix}-litellm-${local.number}.${local.region}.run.app"
  public_url  = var.domain != "" ? "https://${var.domain}" : local.web_url
  public_host = var.domain != "" ? var.domain : replace(local.web_url, "https://", "")
  map_domain  = var.domain != "" && var.enable_domain_mapping
  registry    = "${local.region}-docker.pkg.dev/${local.project}"
}
