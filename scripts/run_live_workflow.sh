#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
uv run python scripts/prepare_runtime.py
uv run python -m agents.verifier.main > runtime/verifier.log 2>&1 &
VERIFIER_PID=$!
uv run python -m agents.remediator.main > runtime/remediator.log 2>&1 &
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
CLIENT_OUTPUT="$(timeout 145s uv run python scripts/m1_session_client.py --workflow 2>&1)"
CLIENT_STATUS=$?
set -e
printf '%s\n' "$CLIENT_OUTPUT"
if [[ "$CLIENT_STATUS" -ne 124 && "$CLIENT_STATUS" -ne 0 ]]; then
  exit "$CLIENT_STATUS"
fi
if ! printf '%s\n' "$CLIENT_OUTPUT" | rg -q 'LIVE_WORKFLOW_RESULT '; then
  echo "Client received no live workflow result." >&2
  exit 1
fi
