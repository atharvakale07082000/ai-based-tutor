#!/usr/bin/env bash
# Install language runtimes into a running Piston service (idempotent).
# The ghcr.io/engineer-man/piston image ships with NO languages — install them once after
# `docker compose up`. Usage:  bash scripts/piston_install.sh  [PISTON_URL]
set -euo pipefail

PISTON_URL="${1:-http://localhost:2000}"

# Languages to install (matches app/services/code_runner.SUPPORTED_LANGUAGES).
LANGS=(python javascript typescript java c "c++" csharp go rust ruby php kotlin swift bash)

echo "Installing language packs into ${PISTON_URL} ..."
for lang in "${LANGS[@]}"; do
  echo "  -> ${lang}"
  curl -fsS -X POST "${PISTON_URL}/api/v2/packages" \
    -H 'Content-Type: application/json' \
    -d "{\"language\": \"${lang}\", \"version\": \"*\"}" >/dev/null \
    && echo "     ok" \
    || echo "     (skipped / already installed / unavailable)"
done

echo "Done. Installed runtimes:"
curl -fsS "${PISTON_URL}/api/v2/runtimes" | head -c 2000 || true
echo
