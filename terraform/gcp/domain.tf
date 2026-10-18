# Needs DNS verification of the domain for the account that runs Terraform (Search Console).
# Cloud Run domain mappings are not offered in every region; set enable_domain_mapping=false
# there and put a load balancer in front instead.
resource "google_cloud_run_domain_mapping" "web" {
  count    = local.map_domain ? 1 : 0
  location = local.region
  name     = var.domain

  metadata {
    namespace = local.project
  }

  spec {
    route_name = google_cloud_run_v2_service.web.name
  }
}
