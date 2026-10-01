#!/usr/bin/env bash
# Creates the 'perennial' macOS user and the shared exchange dirs, and locks down the owner's home.
set -euo pipefail
OWNER="${1:?usage: sudo ./setup-sandbox-user.sh <owner-username>}"
SHARED=/Users/Shared/perennial

if ! id perennial >/dev/null 2>&1; then
  sysadminctl -addUser perennial -fullName "Perennial agent" -password - -home /Users/perennial
  createhomedir -c -u perennial >/dev/null
fi
# The owner's home must not be readable by the agent (dotfiles hold secrets).
chmod 700 "/Users/$OWNER"
# inbox: owner writes snapshots, agent reads. outbox: agent writes, owner's relay reads and moves.
mkdir -p "$SHARED/inbox" "$SHARED/outbox"
chown "$OWNER":staff "$SHARED/inbox" && chmod 755 "$SHARED/inbox"
chown perennial:staff "$SHARED/outbox" && chmod 775 "$SHARED/outbox"
echo "done. Next: log in as perennial once and run 'claude' and 'gh auth login' with the BOT account."
