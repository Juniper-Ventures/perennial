# Perennial Phase 2 — Ideas, Approvals, Dashboard

> **For agentic workers:** implement task by task with TDD. Each task lists its files, the behavior to test first, and the acceptance check. The code lives in the repo. This plan fixes the contracts.

**Goal:** A perennial generates its own ideas every night and builds the best one end to end, with no review. It can ask the owner to approve outside effects (L3), first of all making a build public. A local read-only dashboard shows everything it does.

**Architecture:** Ideas are rows in a new `ideas` table. A nightly ideation run fills it. The best new idea is marked `queued`, and an `IdeaSource` turns queued ideas into normal tasks, so triage, budget, the kill switch and the executor apply unchanged. Builds run in a fresh git repo. With `builds_owner` set, the build is pushed as a *private* repo (L2). Making it public is L3: the perennial writes an `approve` request to the outbox. The owner's relay asks on Telegram in a detached process and writes the reply into a shared approvals dir. The supervisor applies approved actions on a later tick. The dashboard is a stdlib HTTP server bound to 127.0.0.1.

**Tech Stack:** unchanged (Python 3.13 stdlib, pytest, `claude`, `gh`).

---

## Contracts

**Config (new keys, all optional):**

| Key | Default | Meaning |
|---|---|---|
| `autonomy` | — | Now 0..3. 3 = L3 actions are allowed *only* with owner approval. |
| `idea_hour` | 3 | Local hour of the nightly ideation (once per day). |
| `ideas_per_day` | 5 | Ideas generated per ideation run. |
| `idea_context` | `[]` | Files (e.g. exported notes) read as context for ideation. |
| `builds_owner` | `""` | GitHub owner for build repos. Empty = builds stay local. |
| `approvals` | `<home>/approvals` | Dir where the relay writes owner answers. Point it at the shared inbox. |

**Policy:** `require(action, approved=False)`. L4 is always blocked. L3 passes only if `autonomy >= 3 and approved`. L0–L2 pass if `level <= autonomy`.

**Gate:** `Outbox.request_approval(req_id, message)` writes `{"kind":"approve","id":…,"message":…}`. The relay allowlist is `{"notify","approve"}`. For `approve`, the relay calls `ask(message, label, req_id)`. The default `ask` spawns a detached `python3 <cli> "<msg>" --wait --timeout 900 --label perennial-approve` and writes stdout to `<approvals>/<id>.txt` atomically. `Approvals(dir).answer(req_id)` returns `None` while pending, `True` if the reply starts with yes/ja/y/ok/approve/godkend, and `False` otherwise (including timeout).

**Store:**
- Table `ideas(id, title, pitch, value, effort, novelty, status new|queued|dropped, created_at)`, with `add_ideas`, `ideas(status)`, `queue_best_idea()` (score = value·novelty/effort) and `idea_titles()`.
- Table `approvals(id, task_id, action, payload, status pending|approved|denied|done, created_at)`, with `add_approval`, `approvals(status)` and `set_approval`.

**Ideas:** `ideation_prompt(charter, context, existing, n)` and `parse_ideas(text) -> list[dict]` (JSON array, clamped scores, at most n). `IdeaSource(store).fetch()` returns `Task(source="idea:local", ext_id=<idea id>, title, body=pitch)` for queued ideas.

**Executor:** tasks from `idea:` get `git init` in the workspace. After an ok run, the changes are committed. If `builds_owner` is set, `push_own` creates `gh repo create <owner>/perennial-<slug> --private --source <ws> --push`, and an approval `publish` is requested for that repo.

**Supervisor:** each tick, in order: stop check → refresh → triage → run one → **apply approvals** → **maybe ideate** → maybe digest. The digest adds the ideas generated today and pending approvals.

**Dashboard:** `render(store, cfg) -> str` (HTML). `perennial dashboard --port 8787` serves it on 127.0.0.1 only.

## Tasks

1. **Config:** new keys and defaults; autonomy 0..3. Tests: defaults; reject 4; `approvals` override.
2. **Policy:** L3 requires approval. Tests: L3 denied without approval at autonomy 3; allowed with approval at 3; denied with approval at 2; L4 always denied.
3. **Store:** ideas and approvals tables. Tests: add and queue the best idea (score order, only one queued); duplicate titles ignored; approval lifecycle.
4. **Ideas:** prompt and parser. Tests: parses a JSON array inside prose; clamps; caps at n; garbage gives `[]`.
5. **IdeaSource:** tests that queued ideas map to tasks and new ideas do not.
6. **Gate approvals:** the outbox writes an approve request; the relay routes approve to `ask` and rejects unknown kinds; `Approvals.answer` parses yes/no/timeout/pending.
7. **Executor builds:** an idea task inits git and commits. With `builds_owner` it creates a private repo and returns the publish request. Without it, nothing is pushed.
8. **Supervisor:** applies approved publish (`gh repo edit --visibility public --accept-visibility-change-consequences`) and marks it done; denied → done without action. Ideation runs once per day after `idea_hour` and queues one idea. The digest lists ideas and pending approvals.
9. **Dashboard:** render shows the name, spend, tasks by status, recent runs, ideas and approvals; HTML-escapes all task text. The server binds 127.0.0.1.
10. **CLI:** `ideate`, `dashboard`, and `relay --approvals DIR`.
11. **Live smoke:** force an ideation with `perennial ideate`, run ticks until the queued idea is built locally, and check the dashboard renders.

## Result (1 Oct 2026)

- 69 tests pass.
- Live smoke ran as the owner user with builds kept local.
  - `perennial ideate` generated 3 ideas for $0.05–0.1 and queued the best one: "mdlint-tasks", a Markdown checklist linter.
  - One `tick` triaged the idea and built it. The result is a stdlib-only package with a CLI, a README and 18 tests, committed in a fresh git repo. Total spend for the day was $0.61.
  - The 18 tests also pass when run separately.
  - The status page rendered the run, the ideas and the spend.
- Not yet exercised live: the private push to `builds_owner` and the Telegram approval round-trip. Both need the sandbox user and the GitHub App. The unit tests and a stubbed detached `ask` cover them.
