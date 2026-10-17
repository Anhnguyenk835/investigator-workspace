# Our images. CI pushes api and web here.
resource "google_artifact_registry_repository" "images" {
  repository_id = "${var.name_prefix}-images"
  location      = local.region
  format        = "DOCKER"
  description   = "Investigator demo images"

  cleanup_policy_dry_run = false
  cleanup_policies {
    id     = "keep-last-10"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }
  cleanup_policies {
    id     = "delete-the-rest"
    action = "DELETE"
    condition {
      older_than = "2592000s" # 30 days
    }
  }

  depends_on = [google_project_service.api]
}

# Cloud Run pulls only from Google registries. This one fronts ghcr.io so the LiteLLM image
# can be used without copying it by hand.
resource "google_artifact_registry_repository" "ghcr" {
  repository_id = "${var.name_prefix}-ghcr"
  location      = local.region
  format        = "DOCKER"
  mode          = "REMOTE_REPOSITORY"
  description   = "Pull-through cache of ghcr.io"

  remote_repository_config {
    docker_repository {
      custom_repository {
        uri = "https://ghcr.io"
      }
    }
  }

  depends_on = [google_project_service.api]
}

locals {
  litellm_image = "${local.registry}/${google_artifact_registry_repository.ghcr.repository_id}/berriai/litellm-database:v1.99.0"
  # Placeholder for the first apply. CI replaces it with the real image and Terraform leaves it alone.
  placeholder_image = "us-docker.pkg.dev/cloudrun/container/hello"
}
