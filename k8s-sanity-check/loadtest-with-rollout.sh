#!/bin/bash
# Single self-contained script: reset to v1 baseline, start the load
# generator, trigger the v1->v2 rollout a few seconds in, and wait for the
# load generator to finish -- all in one process so the timing between
# "load test running" and "rollout triggered" is guaranteed, not dependent
# on separate tool calls.
set -e
cd "$(dirname "$0")"

kubectl set image deployment/rollout-demo -n rollout-demo app=nginx:1.25-alpine >/dev/null
kubectl rollout status deployment/rollout-demo -n rollout-demo --timeout=60s >/dev/null
echo "$(date +%H:%M:%S) baseline ready: v1, 4/4 — starting load generator"

./loadtest.sh &
LOADPID=$!

sleep 5
echo "$(date +%H:%M:%S) === triggering rollout v1 -> v2 now ==="
kubectl set image deployment/rollout-demo -n rollout-demo app=nginx:1.27-alpine >/dev/null

wait "$LOADPID"
