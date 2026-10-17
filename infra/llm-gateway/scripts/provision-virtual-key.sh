#!/usr/bin/env bash
# Mint a virtual key for one service. Services never hold a provider key.
#
#   LITELLM_MASTER_KEY=sk-... ./provision-virtual-key.sh api
set -euo pipefail

ADMIN_URL=${LLM_GATEWAY_ADMIN_URL:-http://127.0.0.1:4000}

usage() {
  printf 'Usage: %s <api>\n' "$0" >&2
  exit 64
}

[[ $# -eq 1 ]] || usage
: "${LITELLM_MASTER_KEY:?LITELLM_MASTER_KEY must be set}"

case $1 in
  api)
    models='["fast","fast-openai-fallback","fast-anthropic-fallback","strong","strong-openai-fallback","strong-anthropic-fallback"]'
    budget=5              # dollars
    budget_duration=1d    # resets at next UTC midnight
    rpm=120
    tpm=200000
    parallel=16
    ;;
  *) usage ;;
esac

response=$(curl -sS -X POST "${ADMIN_URL}/key/generate" \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"models\": ${models},
       \"max_budget\": ${budget},
       \"budget_duration\": \"${budget_duration}\",
       \"rpm_limit\": ${rpm},
       \"tpm_limit\": ${tpm},
       \"max_parallel_requests\": ${parallel},
       \"key_alias\": \"$1\",
       \"metadata\": {\"service\": \"$1\"}}")

key=$(printf '%s' "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("key",""))')
if [[ -z $key ]]; then
  printf 'key generation failed:\n%s\n' "$response" >&2
  exit 1
fi

printf 'LITELLM_API_KEY=%s\n' "$key"
printf '\nAdd that to the backend .env. Budget $%s / %s, %s rpm, %s tpm.\n' "$budget" "$budget_duration" "$rpm" "$tpm" >&2
