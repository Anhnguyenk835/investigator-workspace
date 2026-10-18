# GCP demo infrastructure

Terraform for the demo: three Cloud Run services (`web`, `api`, `litellm`), Cloud SQL for PostgreSQL 17, Artifact Registry, Secret Manager, a Workload Identity Federation pool for GitHub Actions, an optional domain mapping, and an optional budget and uptime alert. It is sized for a few visitors, not for scale.

```
browser ──► web (nginx, /api proxy) ──► api ──► Cloud SQL
 your domain                             └────► litellm ──► Gemini / OpenAI / Anthropic
GitHub Actions ──► Artifact Registry ──► Cloud Run (api, web)
```

About **$65–70 a month** while running; **$3–5** with `demo_running = false`.

## Before you start

- A GCP project with billing enabled, and `gcloud` and `terraform` (1.6 or newer) installed.
- Your Google account needs permission to create resources in the project (Owner is simplest for a demo).
- If you use a domain: verify it for your Google account at https://search.google.com/search-console, or the domain mapping fails.
- The provider keys for the gateway (at least Gemini) and, for sign-in, a Google OAuth client.

## 1. Apply

```
gcloud auth application-default login
cd terraform/gcp
cp terraform.tfvars.example terraform.tfvars   # fill it in; it is git-ignored
terraform init
terraform plan
terraform apply
```

If the first apply stops with an "API not enabled" error, wait a minute and apply again: enabling an API takes a moment to take effect.

The first apply starts every service from a placeholder image, so it works before any real image exists. Terraform never changes the image afterwards; CI does.

Secrets you leave empty are created empty and not wired; add them later and redeploy the service:

```
printf '%s' "$GEMINI_API_KEY" | gcloud secrets versions add investigator-gemini-api-key --data-file=-
```

Generated secrets (database password, token encryption key, gateway master key) are in the **state file**, which is why `terraform.tfstate` stays local and out of git. If you move the state to a bucket (see `versions.tf`), keep the bucket private.

## 2. Wire up GitHub

`terraform output github_variables` prints five values. In the repository: **Settings → Secrets and variables → Actions → Variables**, create `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_NAME_PREFIX`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOYER_SERVICE_ACCOUNT`, and a GitHub environment named `demo`.

Merging to `main` then builds the images, pushes them to Artifact Registry and deploys `api` and `web`. To deploy right away without waiting, re-run the Release workflow.

## 3. Domain and sign-in

- `terraform output dns_records` lists the records to create at your registrar. Certificates are issued by Google once DNS resolves (minutes to an hour).
- No domain yet: `public_url` is the web service's `run.app` address and works over https as it is.
- `terraform output redirect_uris` lists the redirect URIs to register: the Google OAuth client (sign-in), and the Slack, Atlassian and Notion apps when you connect those sources. Gmail uses the Google client too.
- If the consent screen is in *Testing*, add the people who will sign in as test users.

Cloud Run domain mappings are not offered in every region. If apply reports that for your region, set `enable_domain_mapping = false` and either use another region (for example `us-central1`) or put an external load balancer in front of `web`.

## 4. Load the demo data

The demo corpus and the eight sample investigations live in the database. From your machine, with the repository's seed plan (`platform-be/seed-plan.json`):

```
# terminal 1: reach the database
cloud-sql-proxy $(terraform output -raw sql_connection_name) --port 5443

# terminal 2
cd ../../platform-be
export DATABASE_URL="postgresql://investigator:$(gcloud secrets versions access latest --secret investigator-database-url | sed -E 's#.*investigator:([^@]+)@.*#\1#')@127.0.0.1:5443/investigator"
export LITELLM_BASE_URL="$(terraform -chdir=../terraform/gcp output -json service_urls | jq -r .litellm)"
export LITELLM_API_KEY="$(gcloud secrets versions access latest --secret investigator-litellm-master-key)"
.venv/bin/python -m investigator.devseed export-demo
.venv/bin/python -m investigator.devseed run-samples     # about $1 of model calls
```

## Day to day

| Want | Do |
|---|---|
| Stop paying for compute between demos | `terraform apply -var demo_running=false` (the database is stopped, its data kept) |
| Start it again | `terraform apply` (or `-var demo_running=true`); allow a few minutes for Cloud SQL |
| A fast first answer in a live demo | `-var litellm_always_on=true` |
| Bigger database | `-var sql_tier=db-g1-small` |
| Roll back a release | Re-run the Release workflow of an earlier commit, or `gcloud run deploy investigator-api --image <registry>/investigator-api:sha-xxxxxxx --region <region>` |
| Remove everything | `terraform destroy` (the database is deleted; `sql_deletion_protection` is off by default) |

## Things to know

- `api` runs as exactly one instance with CPU always on: investigations run inside it, and it deletes idle demo sessions. A deploy briefly ends open streams.
- The `api`, `web` and `litellm` services accept requests from the internet. The API signs people in itself, and the gateway requires its master key on every request. If your organisation forbids public Cloud Run services (an `allUsers` policy), these bindings fail and the services need another front.
- The gateway cold-starts in 10–20 s when it was idle. That only delays the first model call.
- The app already caps demo use (investigations and questions per visitor, sessions per IP, a daily spend limit set by `demo_day_cost_usd`). Set a spending cap in each model provider's console as well.
- `terraform plan` needs credentials because it reads the project; without them only `terraform validate` runs.
