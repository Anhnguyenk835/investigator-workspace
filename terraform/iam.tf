resource "google_service_account" "api" {
  account_id   = "${var.name_prefix}-api"
  display_name = "Investigator API"
  depends_on   = [google_project_service.api]
}

resource "google_service_account" "web" {
  account_id   = "${var.name_prefix}-web"
  display_name = "Investigator web"
  depends_on   = [google_project_service.api]
}

resource "google_service_account" "litellm" {
  account_id   = "${var.name_prefix}-litellm"
  display_name = "Investigator LLM gateway"
  depends_on   = [google_project_service.api]
}

# The API reaches the database through the Cloud SQL connector.
resource "google_project_iam_member" "api_sql" {
  project = local.project
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.api.email}"
}

# Each service reads only its own secrets.
resource "google_secret_manager_secret_iam_member" "api" {
  for_each  = toset(local.api_secret_names)
  secret_id = google_secret_manager_secret.s[each.value].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}

resource "google_secret_manager_secret_iam_member" "litellm" {
  for_each  = toset(local.litellm_secret_names)
  secret_id = google_secret_manager_secret.s[each.value].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.litellm.email}"
}

resource "google_secret_manager_secret_iam_member" "litellm_config" {
  secret_id = google_secret_manager_secret.litellm_config.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.litellm.email}"
}
