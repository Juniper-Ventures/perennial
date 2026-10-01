# Install (macOS)

Perennial runs as its own macOS user, `perennial`. The owner (you) keeps a clone too, for the host jobs: the snapshot export and the relay.

## 1. Create the sandbox user (once, as admin)

```bash
git clone https://github.com/Juniper-Ventures/perennial.git ~/perennial
cd ~/perennial && uv sync
sudo deploy/setup-sandbox-user.sh "$USER"
```

This does three things:

- It creates the user `perennial`. You type its password.
- It sets your home to `chmod 700`. macOS homes are group-readable by default, and the agent is in group `staff`, so this step is what keeps it out of your dotfiles and secrets.
- It creates `/Users/Shared/perennial/{inbox,outbox}`.

Check it: `sudo -u perennial cat ~/.zshrc` must say `Permission denied`.

## 2. Set up the agent account (once, as `perennial`)

```bash
sudo -iu perennial
unset ANTHROPIC_API_KEY            # use the claude.ai login, or set a funded key on purpose
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/Juniper-Ventures/perennial.git ~/perennial && cd ~/perennial && uv sync
claude                             # log in once, then /exit
gh auth login                      # use the GitHub App / bot credentials, never your own
mkdir -p ~/.perennial && cp config.example.toml ~/.perennial/config.toml && $EDITOR ~/.perennial/config.toml
~/perennial/.venv/bin/perennial tick   # one manual tick; check with: perennial status
```

## 3. Host jobs (as you)

Write `~/.perennial-host.env` (see the header of `deploy/host-jobs.sh`): todo files, notifier CLI, and the optional root and Airtable keys. The relay calls `python3 <cli> "<message>" --label <label>`. For approvals it runs `<cli> … --wait` in the background and writes your reply into the approvals dir. Reply YES to approve; anything else denies. Then:

```bash
cp deploy/launchd/ai.perennial.host.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.perennial.host.plist
```

## 4. Start the supervisor (as admin)

```bash
deploy/make-supervisor-plist.sh ember /Users/perennial/.perennial/config.toml | sudo tee /Library/LaunchDaemons/ai.perennial.ember.plist >/dev/null
sudo launchctl bootstrap system /Library/LaunchDaemons/ai.perennial.ember.plist
```

The supervisor ticks every 5 minutes. It restarts on crash (`KeepAlive`) and keeps the Mac awake while it runs (`caffeinate -i`). It loads secrets such as `CLAUDE_CODE_OAUTH_TOKEN` from `/Users/perennial/.perennial/env` (chmod 600). A dedicated always-on machine is best: see [mac-mini.md](mac-mini.md).

## Operate

| Need | Command |
|---|---|
| Status | `sudo -u perennial /Users/perennial/perennial/.venv/bin/perennial status` |
| Stop now (kill switch) | `sudo -u perennial /Users/perennial/perennial/.venv/bin/perennial stop` |
| Resume | `… perennial start` |
| Remove completely | `sudo launchctl bootout system/ai.perennial.<name>` and delete the user in System Settings |
| Status page | `sudo -u perennial … perennial dashboard` → http://127.0.0.1:8787 (read-only) |
| Ideas now | `sudo -u perennial … perennial ideate` |
| Logs | `/Users/perennial/.perennial/supervisor.log`, plus the `events` table in `store.sqlite` |
