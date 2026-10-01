# Running a team of perennials

Each perennial has one config, one home dir and one launchd job. They share the same todo files and one `claims.sqlite`. The first perennial to claim a task runs it. A failed run releases the claim, so another one can try.

## Roles (see `examples/`)

| Name | Role | Autonomy | Ideas at night |
|---|---|---|---|
| forge | Builder: code and prototypes; builds its own ideas into private repos | 3 (publishing asks you) | yes |
| sage | Researcher: sourced reports in `RESULT.md` | 2 | no |
| tally | Ops: drafts, checklists and plans; never contacts people | 2 | no |

Triage reads the charter. Each perennial says `skip` to todos outside its role, so the team splits the work by role and the claims stop any overlap.

## Install a perennial

As `perennial`:
```bash
cp examples/builder.toml ~/.perennial/forge.toml
```
As admin:
```bash
deploy/make-supervisor-plist.sh forge /Users/perennial/.perennial/forge.toml | sudo tee /Library/LaunchDaemons/ai.perennial.forge.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/ai.perennial.forge.plist
```
Repeat these steps for `sage` and `tally`.

## Airtable todos

The host job (as you) exports the Airtable table into the shared inbox:
```bash
AIRTABLE_PAT=… perennial export-airtable --base appXXXX --table "TO DO" --out "/Users/Shared/perennial/inbox/TO DO.md"
```
Add `--owner-email you@…` to export only your rows. Add this line to `ai.perennial.host.plist` next to the snapshot export.

## Budget

Each perennial has its own daily cap. The total spend of the team is the sum of the caps. Check `perennial status` per config, or run one status page per perennial with `--port`.
