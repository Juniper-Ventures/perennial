#!/usr/bin/env bash
# Read-only mirror of every (non-archived) repo in a GitHub org, for agents to read.
#   deploy/sync-repos.sh <org> <dest>      e.g. deploy/sync-repos.sh Juniper-Ventures /Users/Shared/juniper-repos
# Auth: GH_TOKEN (a fine-grained token with Contents + Metadata READ only), or an existing `gh auth login`.
# Each repo is a plain checkout of its default branch, hard-reset to the remote on every run, so local
# edits never survive. Files are world-readable (agents run as other macOS users). Writes <dest>/INDEX.md.
set -uo pipefail
ORG="${1:?usage: sync-repos.sh <org> <dest>}"; DEST="${2:?usage: sync-repos.sh <org> <dest>}"
ENV_FILE="${PERENNIAL_HOST_ENV:-$HOME/.perennial-host.env}"
[ -f "$ENV_FILE" ] && set -a && . "$ENV_FILE" && set +a
export PATH="/opt/homebrew/bin:$PATH"
umask 022
mkdir -p "$DEST" && chmod 755 "$DEST"
# git asks gh for credentials, and gh uses GH_TOKEN; no token is ever written into a remote URL.
GIT=(git -c credential.helper= -c "credential.helper=!gh auth git-credential")

LIST=$(gh repo list "$ORG" --limit 500 --no-archived \
  --json name,description,defaultBranchRef,pushedAt,isPrivate \
  --jq '.[] | [.name, (.defaultBranchRef.name // "main"), .pushedAt[0:10], (if .isPrivate then "private" else "public" end), (.description // "" | gsub("[\t\n]"; " "))] | @tsv') \
  || { echo "sync-repos: cannot list $ORG (token?)" >&2; exit 1; }

INDEX="$DEST/INDEX.md.tmp"
{ echo "# $ORG repositories (read-only mirror)"; echo
  echo "Synced $(date '+%Y-%m-%d %H:%M %Z'). One folder per repo, default branch only. Do not edit: changes are overwritten."; echo
  echo "| repo | branch | last push | visibility | description |"; echo "|---|---|---|---|---|"; } > "$INDEX"
ok=0; fail=0
while IFS=$'\t' read -r name branch pushed vis desc; do
  [ -n "$name" ] || continue
  dir="$DEST/$name"
  if [ -d "$dir/.git" ]; then
    "${GIT[@]}" -C "$dir" fetch -q --prune origin "$branch" 2>/dev/null \
      && "${GIT[@]}" -C "$dir" reset -q --hard "origin/$branch" && "${GIT[@]}" -C "$dir" clean -qfdx
  else
    rm -rf "$dir" && "${GIT[@]}" clone -q --single-branch --branch "$branch" "https://github.com/$ORG/$name.git" "$dir" 2>/dev/null
  fi
  if [ $? -eq 0 ]; then ok=$((ok + 1)); else fail=$((fail + 1)); echo "sync-repos: $name failed" >&2; fi
  echo "| $name | $branch | $pushed | $vis | ${desc//|/\\|} |" >> "$INDEX"
done <<< "$LIST"
chmod -R a+rX "$DEST"
mv "$INDEX" "$DEST/INDEX.md" && chmod 644 "$DEST/INDEX.md"
echo "sync-repos: $ok ok, $fail failed -> $DEST"
