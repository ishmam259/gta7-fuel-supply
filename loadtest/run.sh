#!/usr/bin/env bash
# Usage: loadtest/run.sh <vus> [duration]   -> loadtest/results/<vus>-vus.txt + <vus>-vus-stats.txt
set -u
VUS=$1; DUR=${2:-30s}
OUT=loadtest/results/${VUS}-vus.txt; STATS=loadtest/results/${VUS}-vus-stats.txt
: > "$STATS"
( while true; do docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}}' >> "$STATS" 2>/dev/null; done ) &
SAMPLER=$!
MSYS_NO_PATHCONV=1 docker run --rm -i -e BASE_URL=http://host.docker.internal:8090 -e VUS="$VUS" -e DURATION="$DUR" \
  grafana/k6 run - < loadtest/load.js > "$OUT" 2>&1
kill $SAMPLER 2>/dev/null; wait $SAMPLER 2>/dev/null
echo "done $VUS VUs -> $OUT"
