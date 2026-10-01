#!/usr/bin/env bash
# Owner-side jobs, run every 5 minutes by ai.perennial.host. Settings and keys live in ~/.perennial-host.env (chmod 600):
#   PERENNIAL_REPO=$HOME/perennial
#   TODAY_FILES="$HOME/notes/Today.md"                 # optional, space-separated
#   ROOT_API_KEY=...  ROOT_INBOX_PAGE=...  ROOT_RESULTS_PAGE=...   # optional, enables root in + out
#   AIRTABLE_PAT=...  AIRTABLE_BASE=...  AIRTABLE_TABLE="TO DO"  AIRTABLE_OWNER=...   # optional
#   DISTRESS_CLI=$HOME/distress-call/cli.py            # Telegram notifier (send-only is enough)
#   APPROVALS_DIR=/Users/Shared/perennial/inbox/approvals   # optional; needs the Telegram reply receiver on this machine
set -uo pipefail
ENV_FILE="${PERENNIAL_HOST_ENV:-$HOME/.perennial-host.env}"
[ -f "$ENV_FILE" ] && set -a && . "$ENV_FILE" && set +a
REPO="${PERENNIAL_REPO:-$HOME/perennial}"
P="$REPO/.venv/bin/perennial"
INBOX=/Users/Shared/perennial/inbox

# 1. Todo snapshots in
[ -n "${TODAY_FILES:-}" ] && "$REPO/deploy/export-snapshots.sh" $TODAY_FILES
[ -n "${ROOT_INBOX_PAGE:-}" ] && "$P" export-root --page "$ROOT_INBOX_PAGE" --out "$INBOX/root-inbox.md" >/dev/null
[ -n "${AIRTABLE_BASE:-}" ] && "$P" export-airtable --base "$AIRTABLE_BASE" --table "${AIRTABLE_TABLE:-TO DO}" \
  --out "$INBOX/airtable-todo.md" ${AIRTABLE_OWNER:+--owner-email "$AIRTABLE_OWNER"} >/dev/null

# 2. Relay out (notify → Telegram, results → root, approvals → Telegram + answers dir)
ARGS=(relay --outbox /Users/Shared/perennial/outbox --cli "${DISTRESS_CLI:?set DISTRESS_CLI}")
[ -n "${APPROVALS_DIR:-}" ] && ARGS+=(--approvals "$APPROVALS_DIR")
[ -n "${ROOT_RESULTS_PAGE:-}" ] && ARGS+=(--root-parent "$ROOT_RESULTS_PAGE" --root-actor perennial)
"$P" "${ARGS[@]}" >/dev/null
