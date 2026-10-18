terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Local state by default. State holds the generated secrets (database password, keys), so
  # keep it out of git (see .gitignore here). To share it, move it to a private bucket:
  #
  # backend "gcs" {
  #   bucket = "<your-state-bucket>"
  #   prefix = "investigator-demo"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
