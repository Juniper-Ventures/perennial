#!/usr/bin/env bash
# Writes a launchd plist for one named perennial. Secrets (e.g. CLAUDE_CODE_OAUTH_TOKEN) go in
# /Users/perennial/.perennial/env (chmod 600), never in the plist, which is world-readable.
# Writes a launchd plist for one named perennial. Usage: deploy/make-supervisor-plist.sh <name> <config.toml> > out.plist
set -euo pipefail
NAME="${1:?name}"; CONFIG="${2:?config path}"
cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>ai.perennial.${NAME}</string>
  <key>UserName</key><string>perennial</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>-c</string>
    <string>set -a; [ -f "\$HOME/.perennial/env" ] &amp;&amp; . "\$HOME/.perennial/env"; set +a; exec /usr/bin/caffeinate -i /Users/perennial/perennial/.venv/bin/perennial --config "${CONFIG}" loop --every 300</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/Users/perennial/.local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    <key>HOME</key><string>/Users/perennial</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>/Users/perennial/.perennial/${NAME}.log</string>
  <key>StandardErrorPath</key><string>/Users/perennial/.perennial/${NAME}.log</string>
</dict></plist>
PLIST
