#!/usr/bin/env bash
# Creates the personal chat agent for one owner on the mini: macOS user agent-<owner>, uv + Claude Code +
# this repo for that user, ~/.perennial/chat.env (600) and the LaunchDaemon ai.perennial.chat.<owner>.
#   sudo ~/perennial/deploy/setup-chat-agent.sh esben            # Odin, handle odin
#   sudo ~/perennial/deploy/setup-chat-agent.sh nick              # Agent, handle nick-agent
#   sudo ~/perennial/deploy/setup-chat-agent.sh <owner> <Name> <handle>
# It asks for the Claude token (sk-ant-oat…, from `claude setup-token`) and the root agent key (rk_…).
# Nothing is shown. Rerun it to update the code or replace the secrets; chat.toml and chat-mcp.json are kept.
set -euo pipefail
OWNER="${1:?usage: sudo deploy/setup-chat-agent.sh <owner-shortname> [agent-name] [agent-handle]}"
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
[[ "$OWNER" =~ ^[a-z0-9-]+$ ]] || { echo "Owner must be lowercase [a-z0-9-]."; exit 1; }
case "$OWNER" in
  esben) DEF_NAME=Odin; DEF_HANDLE=odin ;;
  *) DEF_NAME=Agent; DEF_HANDLE="$OWNER-agent" ;;
esac
NAME="${2:-$DEF_NAME}"; HANDLE="${3:-$DEF_HANDLE}"
AGENT="agent-$OWNER"; AHOME="/Users/$AGENT"; CFG="$AHOME/.perennial"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ROOT_MCP_SRC="${ROOT_MCP_SRC:-/Users/${SUDO_USER:-$USER}/juniper-root-mcp}"
NODE="${NODE:-/opt/homebrew/bin/node}"
LOGS=/Users/Shared/perennial/logs
LABEL="ai.perennial.chat.$OWNER"; PLIST="/Library/LaunchDaemons/$LABEL.plist"
[ -f "$ROOT_MCP_SRC/server.js" ] && [ -d "$ROOT_MCP_SRC/node_modules" ] \
  || { echo "No root MCP server with node_modules at $ROOT_MCP_SRC (set ROOT_MCP_SRC)."; exit 1; }
[ -x "$NODE" ] || { echo "No node at $NODE (set NODE)."; exit 1; }

# 1. Secrets first, so a bad paste changes nothing.
echo "Paste the Claude token for $AGENT (sk-ant-oat…), then Enter (nothing is shown):"
read -rs RAW; echo
TOKEN=$(printf "%s" "$RAW" | grep -oE "sk-ant-oat[0-9]+-[A-Za-z0-9_-]+" | head -1 || true)
[ -n "$TOKEN" ] || { echo "No sk-ant-oat token found. Nothing changed."; exit 1; }
echo "Paste the root agent key (rk_…), then Enter (nothing is shown):"
read -rs RAW; echo
KEY=$(printf "%s" "$RAW" | grep -oE "rk_[A-Za-z0-9]{40}" | head -1 || true)
unset RAW
[ -n "$KEY" ] || { echo "No rk_ key found. Nothing changed."; exit 1; }

# 2. The OS user. Its home is private; the owner's home stays unreadable to it.
if ! id "$AGENT" >/dev/null 2>&1; then
  sysadminctl -addUser "$AGENT" -fullName "$NAME ($OWNER's agent)" -password - -home "$AHOME"
  createhomedir -c -u "$AGENT" >/dev/null
fi
chmod 700 "$AHOME"
mkdir -p "$LOGS"
touch "$LOGS/chat-$OWNER.log" && chown "$AGENT":staff "$LOGS/chat-$OWNER.log" && chmod 644 "$LOGS/chat-$OWNER.log"

# 3. Code: this checkout and the root MCP server, copied (the agent cannot read the admin's home).
rsync -a --delete --exclude .venv --exclude __pycache__ --exclude .pytest_cache "$REPO/" "$AHOME/perennial/"
rsync -a --delete "$ROOT_MCP_SRC/" "$AHOME/root-mcp/"
chown -R "$AGENT":staff "$AHOME/perennial" "$AHOME/root-mcp"
sudo -u "$AGENT" -H bash -lc '
  set -e; cd ~
  [ -x ~/.local/bin/uv ] || curl -LsSf https://astral.sh/uv/install.sh | sh
  [ -x ~/.local/bin/claude ] || curl -fsSL https://claude.ai/install.sh | bash
  cd ~/perennial && ~/.local/bin/uv sync --no-dev'

# 4. Config (kept if present) and secrets (always replaced).
install -d -o "$AGENT" -g staff -m 700 "$CFG" "$CFG/chat"
if [ ! -f "$CFG/chat.toml" ]; then
  sed -e "s|^agent_name = .*|agent_name = \"$NAME\"|" \
      -e "s|^system_prompt = .*|system_prompt = \"Your owner's root account is $OWNER@juniper.xyz. Prefer short answers. Search root before you answer questions about Juniper.\"|" \
      "$REPO/examples/chat.toml" > "$CFG/chat.toml"
fi
if [ ! -f "$CFG/chat-mcp.json" ]; then
  sed -e "s|/opt/homebrew/bin/node|$NODE|" -e "s|/Users/agent-esben|$AHOME|" \
      -e "s|\"ROOT_AGENT\": \"odin\"|\"ROOT_AGENT\": \"$HANDLE\"|" \
      "$REPO/examples/chat-mcp.json" > "$CFG/chat-mcp.json"
fi
ENVF="$CFG/chat.env"
( umask 077
  touch "$ENVF"
  grep -v -e "^CLAUDE_CODE_OAUTH_TOKEN=" -e "^ROOT_AGENT_KEY=" "$ENVF" > "$ENVF.tmp" || true
  printf "CLAUDE_CODE_OAUTH_TOKEN=%s\nROOT_AGENT_KEY=%s\n" "$TOKEN" "$KEY" >> "$ENVF.tmp"
  mv "$ENVF.tmp" "$ENVF" )
unset TOKEN KEY
chown "$AGENT":staff "$CFG/chat.toml" "$CFG/chat-mcp.json" "$ENVF"
chmod 600 "$ENVF"

# 5. Check the Claude token as the agent.
sudo -u "$AGENT" -H bash -c 'set -a; . ~/.perennial/chat.env; set +a; unset ANTHROPIC_API_KEY
  ~/.local/bin/claude -p --model haiku "Reply with the single word OK"' && echo "TOKEN OK" \
  || echo "WARNING: the Claude token check failed. Fix it and rerun this script."

# 6. The LaunchDaemon. Secrets stay in chat.env; the plist is world-readable.
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>UserName</key><string>$AGENT</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>-c</string>
    <string>set -a; . "\$HOME/.perennial/chat.env"; set +a; unset ANTHROPIC_API_KEY; exec /usr/bin/caffeinate -i "\$HOME/perennial/.venv/bin/perennial" chat --config "\$HOME/.perennial/chat.toml"</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>$AHOME/.local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    <key>HOME</key><string>$AHOME</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$LOGS/chat-$OWNER.log</string>
  <key>StandardErrorPath</key><string>$LOGS/chat-$OWNER.log</string>
</dict></plist>
PLIST
chown root:wheel "$PLIST" && chmod 644 "$PLIST"
launchctl bootout "system/$LABEL" 2>/dev/null || true
launchctl bootstrap system "$PLIST"
echo "done. $NAME ($HANDLE) runs as $AGENT. Log: tail -f $LOGS/chat-$OWNER.log"
