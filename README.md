# Perennial

Always-on local agents that work through your todo lists. An open-source take on OpenAI's Dots, running on your own machine.

- Each perennial runs as its own sandboxed macOS user under launchd.
- It reads todos from Markdown checklists and labelled GitHub issues, triages them, does what it can alone, and opens PRs.
- It reports in one daily digest. A kill switch and budget caps bound it.

Status: phase 1 (core runtime) works end to end: 49 tests, plus a live smoke run where it triaged two todos, skipped the errand and built and tested the code task for $0.26. Install: [docs/install.md](docs/install.md). Design: [docs/design.md](docs/design.md). Plans: [docs/plans/](docs/plans/).

```bash
perennial tick      # one cycle: refresh todos → triage → run one task → maybe digest
perennial loop      # what launchd runs (every 5 min)
perennial status    # spend today and task counts
perennial stop      # kill switch; perennial start to resume
```

License: MIT.
