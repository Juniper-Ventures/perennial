#!/usr/bin/env bash
# Copies the todo files passed as arguments into the agent's inbox. Nothing else leaves the owner's home.
set -euo pipefail
INBOX=/Users/Shared/perennial/inbox
for f in "$@"; do
  [ -f "$f" ] && cp "$f" "$INBOX/$(basename "$f").tmp" && mv "$INBOX/$(basename "$f").tmp" "$INBOX/$(basename "$f")"
done
