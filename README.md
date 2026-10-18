# The Investigator

An evidence-first investigation workspace for Customer Success and Implementation teams. When a customer escalates, the Investigator reads the connected sources (Gmail, Slack, Jira, Confluence, Notion) and reconstructs what happened, who did what, what was promised, what is still unknown and what to do next. Every claim points at the records behind it.

## What it does

- **Connectors.** Each person connects their own accounts. Sources are read-only and read with that person's own permissions.
- **Investigations.** Describe the escalation, choose where to look, and a LangGraph agent gathers records, builds a timeline and drafts findings. A run can pause for a person to review.
- **Workspace.** Summary, Timeline, Findings, Commitments, Gaps and contradictions, Actions and Sources. Any citation opens the evidence behind it (source, time, excerpt).
- **Copilot.** A chat scoped to one investigation. It can list a source's channels, projects or spaces, search inside them, and cite what it finds. Citations that the evidence does not support are removed with a warning.
- **Customer response.** A draft grounded in verified findings, editable, with a human approval step. Nothing is sent from the product.
- **Guardrails and LLM gateway.** Every model call goes through one guarded path and a LiteLLM gateway (see below).

Unknown is a valid answer. Failed, partial and denied sources are reported, never treated as "nothing found".

## Architecture

```
web (React SPA) ──/api──► platform-be (FastAPI) ──► GuardedLlm ──► LLM gateway (LiteLLM) ──► models
                              │  └─ job queue + worker (LangGraph, Postgres checkpoints)
                              └─ connectors: Gmail · Slack · Jira · Confluence · Notion
                                 Postgres: investigations, chat, jobs, audit, sessions
```

| Folder | What |
|---|---|
| `web/` | React 19, Vite, TypeScript (strict), Tailwind CSS v4. Hard-corner design system, primary `#48AFF0`. |
| `platform-be/` | FastAPI, LangGraph, Postgres. Managed with `uv`; tested with pytest, ruff and mypy. |
| `infra/llm-gateway/` | LiteLLM proxy. Services hold a virtual key, never a provider key. `fast` and `strong` routes with fallback models and a per-key daily cap. |
| `terraform/` | `gcp/` (Cloud Run, Cloud SQL, Secret Manager) or `railway/`. Each is its own Terraform root. |
| `deploy/` | Compose file for running the images on a single Docker host. |

## Safety by design

- **Evidence first.** Findings cite record ids that exist; unsupported claims are rejected. Code owns what is checkable (citations, event times, commitment status, coverage); the model reads, extracts and drafts.
- **Read-only.** No step sends or writes anything outside the investigation record.
- **Humans decide.** Findings and the customer draft each wait for a person's approval. State lives in Postgres, so a run survives a restart.
- **Guardrails** (`platform-be/src/investigator/guardrails/`): secret redaction, PII replacement with placeholders, prompt-injection scanning, output sanitising, egress checks, budget limits, a circuit breaker, a kill switch and an audit row for every model call. Each guard is `off`, `monitor` (records what it would do) or `enforce`. By default only secret redaction is enforced. See [docs/guardrails.md](docs/guardrails.md).

## Run it locally

You need Node 20+, Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and Docker.

**1. Database**

```bash
cd platform-be
docker compose up -d db          # Postgres on 127.0.0.1:5442
```

**2. LLM gateway**

```bash
cd infra/llm-gateway
cp .env.example .env             # add GEMINI / OPENAI / ANTHROPIC keys, master and salt keys
docker compose up -d
LITELLM_MASTER_KEY=sk-... ./scripts/provision-virtual-key.sh api   # prints LITELLM_API_KEY
```

**3. API**

```bash
cd platform-be
cp .env.example .env             # set LITELLM_API_KEY, TOKEN_ENCRYPTION_KEY, OAuth client ids
uv sync
uv run uvicorn investigator.api.app:create_app --factory --port 8010
```

Optional: `EMBEDDED_WORKERS=0` on the API and `uv run python -m investigator.worker` as separate workers.

**4. Web**

```bash
cd web
cp .env.example .env
npm install
npm run dev                      # http://localhost:5173, proxies /api to :8010
```

## Checks

```bash
cd platform-be
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests
uv run pytest -q                                  # a scripted model, no LLM key needed
uv run python -m investigator.guardrails.eval     # guardrail eval gate

cd web
npm run lint && npm run build
```

## Video demo

see [video demo](https://www.youtube.com/watch?v=e-k2hVC_3tc)
