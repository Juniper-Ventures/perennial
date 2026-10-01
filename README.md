# Perennial

Always-on local agents that work through your todo lists. An open-source take on OpenAI's Dots, running on your own machine.

- Each perennial runs as its own sandboxed macOS user under launchd.
- It reads todos from Markdown checklists and labelled GitHub issues, triages them, does what it can alone, and opens PRs.
- It reports in one daily digest. A kill switch and budget caps bound it.

Status: phases 1–3 work end to end. Phase 3 runs a team (builder, researcher, ops) that splits one shared queue by role and claims, and adds Airtable todos ([docs/team.md](docs/team.md)). Phase 2 adds nightly ideation (the best idea is built autonomously), owner approval on Telegram for outside effects such as making a build public, and a read-only status page. Phase 1 (core runtime): 49 tests, plus a live smoke run where it triaged two todos, skipped the errand and built and tested the code task for $0.26. Install: [docs/install.md](docs/install.md) · always-on host: [docs/mac-mini.md](docs/mac-mini.md). Design: [docs/design.md](docs/design.md). Plans: [docs/plans/](docs/plans/).

```bash
perennial tick      # one cycle: refresh todos → triage → run one task → maybe digest
perennial loop      # what launchd runs (every 5 min)
perennial status    # spend today and task counts
perennial stop      # kill switch; perennial start to resume
perennial ideate    # generate ideas now and queue the best one for building
perennial dashboard # read-only status page on http://127.0.0.1:8787
perennial export-airtable --base appX --table "TO DO" --out inbox/TO\ DO.md   # host side
```

License: MIT.
