#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
uv run python scripts/prepare_runtime.py
ADPROOF_TRANSPORT_PROBE=1 uv run python -m agents.verifier.main > runtime/verifier.log 2>&1 &
VERIFIER_PID=$!
ADPROOF_TRANSPORT_PROBE=1 uv run python -m agents.remediator.main > runtime/remediator.log 2>&1 &
REMEDIATOR_PID=$!
ADPROOF_TRANSPORT_PROBE=1 uv run python -m agents.orchestrator.main > runtime/orchestrator.log 2>&1 &
ORCHESTRATOR_PID=$!
cleanup() {
  kill "$ORCHESTRATOR_PID" "$REMEDIATOR_PID" "$VERIFIER_PID" 2>/dev/null || true
  wait "$ORCHESTRATOR_PID" "$REMEDIATOR_PID" "$VERIFIER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
for port in 8100 8101 8102; do
  ready=0
  for _ in $(seq 1 30); do
    if curl --fail --silent "http://127.0.0.1:${port}/health" >/dev/null; then
      ready=1
      break
    fi
    sleep 1
  done
  if [[ "$ready" != 1 ]]; then
    echo "Agent health check failed on port ${port}" >&2
    exit 1
  fi
done
set +e
CLIENT_OUTPUT="$(timeout 15s uv run python scripts/m1_session_client.py 2>&1)"
CLIENT_STATUS=$?
set -e
if [[ "$CLIENT_STATUS" -ne 124 && "$CLIENT_STATUS" -ne 0 ]]; then
  printf '%s\n' "$CLIENT_OUTPUT"
  exit "$CLIENT_STATUS"
fi
printf '%s\n' "$CLIENT_OUTPUT"
PROOF_LINE="$(printf '%s\n' "$CLIENT_OUTPUT" | rg 'M1_PROOF ' | tail -n 1 || true)"
if [[ -z "$PROOF_LINE" ]]; then
  echo "Client did not receive both session-bound replies." >&2
  exit 1
fi
PROOF_JSON="${PROOF_LINE#*M1_PROOF }"
PROOF_JSON="$PROOF_JSON" uv run python -c \
  'import json, os; proof=json.loads(os.environ["PROOF_JSON"]); assert proof["both_match"], json.dumps(proof); print("M1 session proof passed.")'
