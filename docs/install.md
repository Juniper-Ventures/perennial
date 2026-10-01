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

Edit `deploy/launchd/ai.perennial.host.plist`. It must point to your todo files and to your notifier CLI. The relay calls `python3 <cli> "<message>" --label <label>`. Then:

```bash
cp deploy/launchd/ai.perennial.host.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.perennial.host.plist
```

## 4. Start the supervisor (as admin)

```bash
sudo cp deploy/launchd/ai.perennial.supervisor.plist /Library/LaunchDaemons/
sudo launchctl bootstrap system /Library/LaunchDaemons/ai.perennial.supervisor.plist
```

The supervisor ticks every 5 minutes, restarts on crash (`KeepAlive`), and keeps the Mac awake while it runs (`caffeinate -i`).

## Operate

| Need | Command |
|---|---|
| Status | `sudo -u perennial /Users/perennial/perennial/.venv/bin/perennial status` |
| Stop now (kill switch) | `sudo -u perennial /Users/perennial/perennial/.venv/bin/perennial stop` |
| Resume | `… perennial start` |
| Remove completely | `sudo launchctl bootout system/ai.perennial.supervisor` and delete the user in System Settings |
| Logs | `/Users/perennial/.perennial/supervisor.log`, plus the `events` table in `store.sqlite` |
