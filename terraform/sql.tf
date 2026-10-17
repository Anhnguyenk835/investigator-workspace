resource "random_id" "sql" {
  byte_length = 2
}

# Cloud SQL instance names cannot be reused for a week after deletion, hence the suffix.
resource "google_sql_database_instance" "main" {
  name                = "${var.name_prefix}-${random_id.sql.hex}"
  database_version    = "POSTGRES_17"
  region              = local.region
  deletion_protection = var.sql_deletion_protection

  settings {
    tier              = var.sql_tier
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_size         = var.sql_disk_gb
    disk_type         = "PD_SSD"
    disk_autoresize   = true

    # Stopped, the instance costs only its storage.
    activation_policy = var.demo_running ? "ALWAYS" : "NEVER"

    backup_configuration {
      enabled = true
      backup_retention_settings {
        retained_backups = 7
      }
    }

    # Public address, but no network is authorised: the only way in is the Cloud SQL
    # connector (Cloud Run, or the Auth Proxy from a laptop), which uses IAM and TLS.
    ip_configuration {
      ipv4_enabled = true
    }
  }

  depends_on = [google_project_service.api]
}

resource "google_sql_database" "app" {
  name     = "investigator"
  instance = google_sql_database_instance.main.name
}

resource "random_password" "db" {
  length  = 32
  special = false # goes into a URL
}

resource "google_sql_user" "app" {
  name     = "investigator"
  instance = google_sql_database_instance.main.name
  password = random_password.db.result
}

locals {
  # Cloud Run mounts the connector as a unix socket under /cloudsql.
  database_url = "postgresql://investigator:${random_password.db.result}@/investigator?host=/cloudsql/${google_sql_database_instance.main.connection_name}"
}
