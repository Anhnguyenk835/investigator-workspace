# Railway demo infrastructure

Terraform for the demo on [Railway](https://railway.com): one project with four services and a volume. Only `web` is public; the others talk over Railway's private network (`<service>.railway.internal`).

```
browser ──► web (nginx, /api proxy) ──► api ──► postgres (volume)
 your domain                             └────► litellm ──► Gemini / OpenAI / Anthropic
```

| Service | Source | Notes |
|---|---|---|
| `postgres` | `postgres:17-alpine` image, volume at `/var/lib/postgresql/data` | Reachable only inside the project, unless `expose_database = true` |
| `litellm` | Built by Railway from `infra/llm-gateway/Dockerfile` (your GitHub repo) | Routes baked in; needs the Railway GitHub app on the repo |
| `api` | `ghcr.io/<owner>/investigator-api:<tag>` | One replica: investigations run inside the process |
| `web` | `ghcr.io/<owner>/investigator-web:<tag>` | Public `*.up.railway.app` address, or your domain |

Cost is Railway usage-based (CPU, memory, volume, egress) on top of the plan fee; it depends on how much the services run. Check the project's Usage page after a day.

## Before you start

- A Railway account on a plan that allows a project with a volume, and `terraform` (1.6 or newer).
- A Railway token from https://railway.com/account/tokens (account or workspace token): `export RAILWAY_TOKEN=...`
- The Release workflow has pushed the images to GHCR (merge to `main` once). If the packages are private, set `ghcr_username` and `ghcr_token` (a token with `read:packages`), or make the packages public.
- Install the Railway GitHub app on the repository (Railway → Account Settings → Integrations), or the gateway cannot be built.
- Provider keys for the gateway (at least Gemini) and, for sign-in, a Google OAuth client.

## 1. Apply

```
export RAILWAY_TOKEN=...
cd terraform/railway
cp terraform.tfvars.example terraform.tfvars   # fill it in; it is git-ignored
terraform init
terraform plan
terraform apply
```

Services start building and deploying while variables are still being applied, so the first deploy of `api` and `web` may fail once and restart when its variables arrive. If one stays failed, redeploy it from the dashboard.

Secrets you leave empty are not set; add them later in the dashboard (service → Variables) or in `terraform.tfvars` and apply again.

Generated secrets (database password, token encryption key, gateway master key) are in the **state file**, so `terraform.tfstate` stays local and out of git.

## 2. Domain and sign-in

- No domain yet: `terraform output public_url` is the `up.railway.app` address and works over https as it is.
- Custom domain: set `domain`, apply, then create the records from `terraform output dns_records` at your registrar. Railway issues the certificate once DNS resolves.
- `terraform output redirect_uris` lists the redirect URIs to register with the Google OAuth client (sign-in), and with the Slack, Atlassian and Notion apps when you connect those sources.
- If the Google consent screen is in *Testing*, add the people who will sign in as test users.

## 3. Load the demo data

The demo corpus and the sample investigations live in the database. Open a temporary public proxy to Postgres, load, close it:

```
terraform apply -var expose_database=true

cd ../../platform-be
export DATABASE_URL="$(terraform -chdir=../terraform/railway output -raw database_url_for_seeding)"
.venv/bin/python -m investigator.devseed export-demo

cd ../terraform/railway
terraform apply -var expose_database=false
```

`run-samples` (about $1 of model calls) also needs the gateway, which is private. Skip it, or give `litellm` a public domain in the dashboard for the duration and set `LITELLM_BASE_URL` to it and `LITELLM_API_KEY` to `terraform output -raw litellm_master_key`.

The proxy speaks plain Postgres over the internet, protected only by the generated password, so keep it closed except while loading.

## Day to day

| Want | Do |
|---|---|
| Deploy a new release | Set `image_tag = "sha-xxxxxxx"` (a commit tag from GHCR) and `terraform apply`. The default tag `staging` moves, and Railway does not redeploy on its own: redeploy `api` and `web` from the dashboard |
| Stop paying | `terraform destroy` (the database and its volume are deleted). Railway has no pause switch in Terraform; you can also remove the services' deployments in the dashboard |
| Roll back | Set `image_tag` to an earlier commit's tag and apply |
| See logs | Dashboard → service → Deployments, or `railway logs` |

## Things to know

- `api` is pinned to one replica. Do not scale it: investigation workers and the idle-session sweep run inside it, and chat and progress streams stay open for minutes.
- `web` finds `api` by name on the private network, through nginx with the resolver `[fd12::10]` (`dns_resolver`). Environments created since late 2025 support IPv4 and IPv6 there. If `/api` returns 502 on an older environment, enable IPv4 and IPv6 private networking for it, or bind the API to `::`.
- The `api` and `web` services accept requests from the internet through `web`; the API does its own sign-in. `litellm` and `postgres` have no public address.
- Unlike the GCP setup there is no budget alert or uptime check here. Set a usage limit in the Railway dashboard, and a spending cap in each model provider's console. The app also caps demo use (`demo_day_cost_usd`).
- Terraform changes to a service's variables redeploy it. Changing `image_tag` replaces the service's source, which also redeploys it.
