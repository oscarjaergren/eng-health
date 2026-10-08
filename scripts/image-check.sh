#!/usr/bin/env bash
#
# Runs eng-health:latest and checks what only the built image shows. Build it first with
# `mise run image`.
#
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# Compressed MB. pyarrow, pandas and plotly are most of it; a jump usually means dev
# dependencies or a build tool reached the runtime layer.
CEILING_MB=190

fail() { echo "error: $*" >&2; exit 1; }

# A random local port, so a dashboard already running on 8501 doesn't get in the way.
cid=$(docker run -d -p 127.0.0.1::8501 -e MOCK_MODE=true eng-health:latest)
cleanup() {
  local status=$?
  [ "$status" -eq 0 ] || docker logs "$cid" # the logs only matter when something failed
  docker rm -f "$cid" >/dev/null
  exit "$status"
}
trap cleanup EXIT
url="http://$(docker port "$cid" 8501 | head -1)"

curl -fs --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null "$url/_stcore/health" ||
  fail "the dashboard never answered its health check."

[ "$(docker exec "$cid" id -u)" != 0 ] || fail "the image runs as root."
docker exec "$cid" eng-health --version >/dev/null || fail "the sync engine doesn't run."
# The dashboard reads schema.sql from beside its package; a missing file only fails at runtime.
docker exec "$cid" python -c "import eng_health.store" || fail "the dashboard can't load schema.sql."
if docker exec "$cid" python -c "import pytest" 2>/dev/null; then
  fail "dev dependencies are installed in the image."
fi

# Gzipped, so it measures compressed size whichever Docker image store is in use.
mb=$(( $(docker save eng-health:latest | gzip -c | wc -c) / 1048576 ))
echo "Image size (compressed): $mb MB"
[ "$mb" -le "$CEILING_MB" ] || fail "the image is $mb MB, over the $CEILING_MB MB ceiling."
