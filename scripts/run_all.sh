#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
uv run python scripts/prepare_runtime.py
uv run python -m agents.verifier.main > runtime/verifier.log 2>&1 &
VERIFIER_PID=$!
uv run python -m agents.remediator.main > runtime/remediator.log 2>&1 &
REMEDIATOR_PID=$!
uv run python -m agents.generator.main > runtime/generator.log 2>&1 &
GENERATOR_PID=$!
uv run python -m agents.orchestrator.main > runtime/orchestrator.log 2>&1 &
ORCHESTRATOR_PID=$!
cleanup() {
  kill "$ORCHESTRATOR_PID" "$GENERATOR_PID" "$REMEDIATOR_PID" "$VERIFIER_PID" 2>/dev/null || true
  wait "$ORCHESTRATOR_PID" "$GENERATOR_PID" "$REMEDIATOR_PID" "$VERIFIER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
for port in 8100 8101 8102 8103; do
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
echo "All local agents are healthy. Press Ctrl-C to stop them."
wait
