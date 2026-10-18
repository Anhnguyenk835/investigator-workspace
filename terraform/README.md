# Infrastructure

Two ways to host the same app (`web`, `api`, the `litellm` gateway and Postgres). Pick one.

| Folder | Host | Good for |
|---|---|---|
| [`gcp/`](gcp/README.md) | Google Cloud: Cloud Run, Cloud SQL, Artifact Registry, Secret Manager, GitHub deploys through Workload Identity | The demo with a budget guard, a stop switch and CI deploys |
| [`railway/`](railway/README.md) | Railway: four services and a volume in one project | The quickest way to a public URL with the least setup |

Each folder is its own Terraform root with its own state. Run Terraform from inside it.
