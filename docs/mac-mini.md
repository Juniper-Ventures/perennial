# Mac mini runbook (always-on host)

This is the order we use to run a perennial team on a dedicated Mac mini. Steps marked **at the mini** need a keyboard or Screen Sharing once. Everything else works over SSH.

## 0. At the mini (5 minutes, once)

1. System Settings → General → Sharing → turn on **Remote Login**. Allow your admin user only.
2. System Settings → Energy: turn on **Prevent automatic sleeping when the display is off** and **Start up automatically after a power failure**.
3. From your laptop, copy your SSH key: `ssh-copy-id <you>@<mini>.local`.

## 1. Tools (as your admin user)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install gh pandoc git
curl -LsSf https://astral.sh/uv/install.sh | sh
curl -fsSL https://claude.ai/install.sh | bash      # Claude Code
git clone https://github.com/Juniper-Ventures/perennial.git ~/perennial && cd ~/perennial && uv sync
```

## 2. Claude Code login for headless use

On any machine where you are logged in to Claude: `claude setup-token`. It prints a long-lived token for your subscription. You will store it in step 3, only in the agent's private env file.

## 3. Agent user and team

```bash
sudo ~/perennial/deploy/setup-sandbox-user.sh "$USER"
sudo -iu perennial bash -lc '
  curl -LsSf https://astral.sh/uv/install.sh | sh
  curl -fsSL https://claude.ai/install.sh | bash
  git clone https://github.com/Juniper-Ventures/perennial.git ~/perennial && cd ~/perennial && ~/.local/bin/uv sync
  mkdir -p ~/.perennial && touch ~/.perennial/env && chmod 600 ~/.perennial/env
  for r in builder:forge researcher:sage ops:tally; do cp examples/${r%%:*}.toml ~/.perennial/${r##*:}.toml; done'
# put the token from step 2 into the agent's env file (no echo to the terminal):
sudo -u perennial bash -c 'read -rs T; printf "CLAUDE_CODE_OAUTH_TOKEN=%s\n" "$T" > ~/.perennial/env'
```

GitHub for the agents: create a GitHub App in Juniper-Ventures with repository contents, issues and pull requests (read/write), installed on the sandbox and build repos only. Then log in with `sudo -iu perennial gh auth login`. Until then, set `builds_owner = ""` in `forge.toml` and remove the `github` source.

## 4. Host jobs (as you)

```bash
cat > ~/.perennial-host.env <<'ENV'
PERENNIAL_REPO=$HOME/perennial
ROOT_API_KEY=<root key>
ROOT_INBOX_PAGE=<inbox page id>
ROOT_RESULTS_PAGE=<results page id>
AIRTABLE_PAT=<airtable token>
AIRTABLE_BASE=appbL6ewYvsnzG67e
AIRTABLE_TABLE=TO DO
DISTRESS_CLI=$HOME/distress-call/cli.py
ENV
chmod 600 ~/.perennial-host.env
cp ~/perennial/deploy/launchd/ai.perennial.host.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.perennial.host.plist
```

`DISTRESS_CLI` sends Telegram messages. Copy `~/distress-call` and `~/.claude/channels/distress/` from the laptop. Sending works from any machine. Approval replies are received by the Telegram daemon on the laptop, so run the team at `autonomy = 2` (no approvals) until that daemon moves to the mini.

## 5. Start the team

```bash
for n in forge sage tally; do
  ~/perennial/deploy/make-supervisor-plist.sh $n /Users/perennial/.perennial/$n.toml | sudo tee /Library/LaunchDaemons/ai.perennial.$n.plist >/dev/null
  sudo launchctl bootstrap system /Library/LaunchDaemons/ai.perennial.$n.plist
done
```

## 6. Check

- `sudo -u perennial /Users/perennial/perennial/.venv/bin/perennial --config /Users/perennial/.perennial/forge.toml status`
- Logs: `tail /Users/Shared/perennial/logs/forge.log` (readable without sudo).
- Add a bullet to the root **Inbox** page. Within about 10 minutes, a page `agent: task` appears under **Results**.
- Kill switch for one perennial: `… --config …/forge.toml stop`. For all of them: `sudo launchctl bootout system/ai.perennial.<name>`.

## 7. Personal chat agents (root)

Each owner gets one agent that answers their root chat (`#agent`) and `@<handle>` mentions in their comments. It runs as its own macOS user (`agent-esben`, `agent-nick`) with its own Claude token and root agent key, so it sees only that owner's private pages plus the shared pages.

1. In root, create the owner's agent key (`rk_…`, shown once). On a logged-in machine, run `claude setup-token` for the `sk-ant-oat…` token.
2. Copy the root MCP server to the mini once: `~/juniper-root-mcp` with `server.js` and `node_modules` (override with `ROOT_MCP_SRC=…`).
3. Run `sudo ~/perennial/deploy/setup-chat-agent.sh esben` (or `nick`). It creates the user, installs uv, Claude Code and this checkout for it, asks for the token and the key (nothing is shown), writes `~/.perennial/chat.env` (600), `chat.toml` and `chat-mcp.json`, checks the token, and starts the LaunchDaemon `ai.perennial.chat.<owner>`.
4. Check: `tail -f /Users/Shared/perennial/logs/chat-esben.log`, then send a message in root. To stop: `sudo launchctl bootout system/ai.perennial.chat.esben`.

Rerun the script to update the code or replace the secrets. It keeps `chat.toml` and `chat-mcp.json`. Hard rules (no money, no messages as the owner, no credentials, no page deletes, private stays private) are in the system prompt and cannot be configured away.
