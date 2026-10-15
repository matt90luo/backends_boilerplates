#!/usr/bin/env bash
# End-to-end smoke test against a running API.
#
#   make migrate seed && make dev        # in one terminal
#   make smoke                           # in another
#
# It registers a throwaway user, lets the seeded admin grant credits, invokes the
# built-in `echo` service and reads the usage log back.
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@tinysaas.local}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin12345}"
PASSWORD="Smoke${RANDOM}pass1"
EMAIL="smoke-${RANDOM}@example.com"
API="${BASE_URL}/api/v1"

need() { command -v "$1" >/dev/null || { echo "missing dependency: $1" >&2; exit 1; }; }
json() { python3 -c "import json,sys; data=json.load(sys.stdin); print(eval('data' + sys.argv[1]))" "$1"; }

need curl
need python3

echo "==> health"
curl -fsS "${BASE_URL}/healthz" | json "['data']['status']" >/dev/null
echo "    ok"

echo "==> register ${EMAIL}"
SESSION=$(curl -fsS -X POST "${API}/auth/register" -H 'Content-Type: application/json' \
  -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}")
ACCESS=$(echo "${SESSION}" | json "['data']['access_token']")

echo "==> login as admin ${ADMIN_EMAIL}"
ADMIN_SESSION=$(curl -fsS -X POST "${API}/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}")
ADMIN_TOKEN=$(echo "${ADMIN_SESSION}" | json "['data']['access_token']")

echo "==> grant 10 credits"
USER_ID=$(curl -fsS "${API}/users/me" -H "Authorization: Bearer ${ACCESS}" | json "['data']['id']")
curl -fsS -X POST "${API}/admin/users/${USER_ID}/credits" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" -H 'Content-Type: application/json' \
  -d '{"amount":10,"reason":"smoke test"}' >/dev/null
echo "    wallet: $(curl -fsS "${API}/billing/wallet" -H "Authorization: Bearer ${ACCESS}" | json "['data']['balance']") credits"

echo "==> invoke echo"
curl -fsS -X POST "${API}/services/echo/execute" \
  -H "Authorization: Bearer ${ACCESS}" -H 'Content-Type: application/json' \
  -d '{"hello":"world"}'
echo
echo "    wallet: $(curl -fsS "${API}/billing/wallet" -H "Authorization: Bearer ${ACCESS}" | json "['data']['balance']") credits"

echo "==> usage logs"
curl -fsS "${API}/me/invocations" -H "Authorization: Bearer ${ACCESS}" | json "['data']['total']" >/dev/null
curl -fsS "${API}/me/invocations" -H "Authorization: Bearer ${ACCESS}" \
  | python3 -c "import json,sys; rows=json.load(sys.stdin)['data']['items']; print('\n'.join(f\"    {r['service_slug']} {r['status']} charged={r['credits_charged']} latency={r['latency_ms']}ms\" for r in rows))"

echo "==> admin can see the same user's logs"
curl -fsS "${API}/admin/users/${USER_ID}/invocations" -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  | python3 -c "import json,sys; print('    total:', json.load(sys.stdin)['data']['total'])"

echo
echo "smoke test passed ✅"
