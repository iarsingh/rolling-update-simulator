#!/bin/bash
# Continuous request loop against the Service while a rollout is in progress.
# One line per failed request (immediately) plus a summary every 50 requests,
# so silence during the run is itself evidence nothing failed.
URL="http://127.0.0.1:8080/"
TOTAL=900   # ~90s at ~10 req/s
fails=0

for i in $(seq 1 "$TOTAL"); do
  start=$(date +%s%3N)
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "$URL")
  end=$(date +%s%3N)
  ms=$((end - start))
  ts=$(date +%H:%M:%S)

  if [ "$code" != "200" ]; then
    fails=$((fails + 1))
    echo "$ts req#$i FAIL status=${code:-timeout} latency=${ms}ms total_fails=$fails"
  fi

  if [ $((i % 50)) -eq 0 ]; then
    echo "$ts req#$i ok-so-far total_fails=$fails"
  fi

  sleep 0.1
done

echo "$(date +%H:%M:%S) DONE total_requests=$TOTAL total_fails=$fails"
