#!/usr/bin/env bash
# Scaffolds the Logseq graph directories on the NAS and deploys config files.
#
# Usage:
#   ./infra/logseq/setup-nas.sh <nas-user@nas-host>
#
# Example:
#   ./infra/logseq/setup-nas.sh brandon.olin@192.168.68.58
#
# Safe to re-run — mkdir -p and cat are both idempotent.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <nas-user@nas-host>" >&2
  exit 1
fi

NAS="$1"
LOGSEQ_ROOT="/volume1/data/logseq"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "→ Creating graph directories on ${NAS} ..."

ssh "${NAS}" "
  set -e
  for graph in household-graph brandon-private; do
    for sub in pages journals assets logseq/bak logseq/version-files; do
      mkdir -p '${LOGSEQ_ROOT}'/"'$graph'"/"'$sub'"
    done
    echo \"  ✓ ${LOGSEQ_ROOT}/\$graph\"
  done
"

echo "→ Deploying config.edn files ..."

ssh "${NAS}" "cat > ${LOGSEQ_ROOT}/household-graph/logseq/config.edn" \
  < "${SCRIPT_DIR}/household-graph/logseq/config.edn"
echo "  ✓ household-graph/logseq/config.edn"

ssh "${NAS}" "cat > ${LOGSEQ_ROOT}/brandon-private/logseq/config.edn" \
  < "${SCRIPT_DIR}/brandon-private/logseq/config.edn"
echo "  ✓ brandon-private/logseq/config.edn"

echo ""
echo "Done. Both graphs are ready at ${LOGSEQ_ROOT} on ${NAS}."
