# LLM gateway

LiteLLM proxy. Every model call goes through it. Services hold a **virtual
key**, never a provider key, so a key can be revoked, budgeted or rate-limited
without redeploying. Provider keys live only in `infra/llm-gateway/.env`
(git-ignored); never in `web/`.

## Setup

    cd infra/llm-gateway
    cp .env.example .env

Fill in `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, then:

    echo "LITELLM_MASTER_KEY=sk-$(openssl rand -hex 24)"
    echo "LITELLM_SALT_KEY=$(openssl rand -hex 24)"

`LITELLM_MASTER_KEY` is an admin credential (port is bound to localhost).
`LITELLM_SALT_KEY` encrypts stored keys — generate once, never change.

    docker compose up -d
    LITELLM_MASTER_KEY=sk-... ./scripts/provision-virtual-key.sh api

Put the printed `LITELLM_API_KEY` in the backend `.env`, with
`LITELLM_BASE_URL=http://127.0.0.1:4000`.

## Routes

| Route | Primary | Fallback 1 | Fallback 2 |
| --- | --- | --- | --- |
| `fast` | `gemini-3.1-flash-lite` | `gpt-4o-mini` | `claude-haiku-4-5` |
| `strong` | `gemini-3.5-flash-lite` | `gpt-4.1-mini` | `claude-haiku-4-5` |

All cheap-tier. To upgrade a route later, edit `config.yaml` only; callers
keep using the same route names. The default virtual key is capped at $5/day.

## Smoke test

    curl -s http://127.0.0.1:4000/v1/chat/completions \
      -H "Authorization: Bearer $LITELLM_API_KEY" -H "Content-Type: application/json" \
      -d '{"model":"fast","messages":[{"role":"user","content":"ping"}]}'
