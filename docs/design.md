# Perennial — always-on local agents

Status: design, 1 Oct 2026. Owner: Esben Kran.

Perennial is an open-source, local version of OpenAI's Dots. It runs named agents ("perennials") on one machine. Each perennial stays on all the time, reads the open todos in your projects, decides what it can do alone, does it, and proposes and builds new ideas. People step in only at a few hard gates.

## 1. What OpenAI shipped (Dots, 29 Sep 2026)

Facts from the launch coverage:

- A Dot is a named, persistent agent with **its own cloud computer and browser**. You can open its computer and watch the work. ([Tom's Guide](https://www.tomsguide.com/ai/openai-gave-chatgpt-a-virtual-computer-to-run-errands-for-you), [DEV](https://dev.to/siddhesh_surve/the-always-on-agent-is-here-openai-just-launched-dots-and-it-changes-how-we-code-5779))
- It runs on GPT-6 Astra. It keeps several projects moving at once and takes new work without new threads. ([VentureBeat](https://venturebeat.com/technology/openai-launches-dots-always-on-ai-agent-coworkers-and-chatgpt-space-where-they-can-collaborate-with-human-teams), [AI Weekly](https://aiweekly.co/alerts/openai-unveils-dots-always-on-chatgpt-agents-at-devday))
- It reaches its user through ChatGPT, Slack, Teams and voice; SMS is planned. It connects to 4,000+ apps through plugins.
- It learns preferences from corrections.
- **Safety model:**
  - The VM is isolated from your laptop by default. Local access needs explicit permission.
  - Credentials are used without being exposed to the model.
  - Background research runs **read-only**: a Dot "can't independently send a message, delete a file or spend your money". Those actions need approval.
- Price: one Dot is included in ChatGPT Pro ($100/month). Enterprise gets "specialist dots".

What we copy: persistent identity, its own isolated computer, many parallel projects, reach-me-anywhere messaging, learning from corrections, a dashboard to watch the work.

What we change: it runs locally on our own hardware, uses any model (Claude Code first), is fully open source, and its work queue comes from our existing todo systems, not from chat.

## 2. Requirements

1. **Always on.** It survives reboots and crashes and restarts itself.
2. **Reads todos** from the places where they already live: Markdown checklists (Obsidian), GitHub issues, and later root pages and Airtable.
3. **Acts alone** on work it can finish and reverse: code, research, drafts, prototypes.
4. **Generates ideas** and builds the best ones end to end with no human review.
5. **Reports** in one short daily digest. It interrupts a human only to ask for a gate approval.
6. **Public repo, private config.** Nothing personal (paths, tokens, todo text) is committed.

## 3. Architecture

```
            ┌──────────────── host (owner user) ──────────────────┐
            │  sources (read-only snapshots)    gate service      │
            │  Today.md · GH issues · root      notify · approve  │
            └───────────┬──────────────────────────▲──────────────┘
                        │ snapshot files            │ HTTP (localhost)
            ┌───────────▼──────────────────────────┴──────────────┐
            │  perennial user (sandbox)                            │
            │  supervisor (launchd, KeepAlive)                     │
            │   tick: STOP? → refresh → triage → pick → execute    │
            │  store.sqlite (tasks, runs, events)                  │
            │  workspaces/<task-id>/  (git repo per task)          │
            │  executor → `claude -p` (headless Claude Code)       │
            └──────────────────────────────────────────────────────┘
```

**Components**

| Component | Job |
|---|---|
| `config` | Loads `~/.perennial/config.toml`: perennials, sources, budgets, autonomy. Never in the repo. |
| `store` | SQLite with three tables. `tasks` (source, external id, title, status, triage), `runs` (task, start, end, cost, exit, summary), `events` (append-only log). |
| `sources/*` | Adapters. Each returns `Task` objects. Read-only. |
| `triage` | One cheap model call per new task. It returns `do` / `ask` / `skip` plus effort and value scores. |
| `policy` | Kill switch, daily budget, concurrency, and the autonomy check for every outbound action. |
| `executor` | Makes a workspace and runs Claude Code headless with the perennial's charter, a budget cap and a time limit. It records the result. |
| `gate` | The only path out of the sandbox: notify, approval request, append to the human's log, open a PR. |
| `supervisor` | The tick loop under launchd. |
| `ideas` (phase 2) | A nightly ideation run. It writes `ideas.md`, scores ideas and turns the top one into a `build` task. |
| `dashboard` (phase 3) | A local web view of the queue, runs, diffs and costs: "open the Dot's computer". |

**Model runtime.** The executor runs the `claude` CLI (`claude -p --output-format json --max-budget-usd N --permission-mode bypassPermissions`). It is already installed and authenticated. The runner interface takes a command, so `codex` or `omp` can replace it.

## 4. The autonomy model

The goal is full autonomy for building, without the failure modes seen in public investigations of rogue agents in 2026 ([Asymmetric Security](https://www.asymmetricsecurity.com/newsroom/rogue-agents-investigation/), [Transluce](https://transluce.org/us-canada-gov)): sandbox escape, account creation, data sent out through third parties. The answer is to put the boundary around the **machine**, not around each action.

| Level | Actions | Default |
|---|---|---|
| L0 Read | Read snapshots and public web | Always allowed |
| L1 Build | Any change inside its own sandbox user and workspaces; install packages; run code | **Always allowed, no review** |
| L2 Ship to own space | Push to repos owned by the perennial's own GitHub account; open PRs on our repos | **Always allowed** (a PR is not a merge) |
| L3 Outside effects | Message a human other than the owner, publish publicly, merge to `main` of a human repo, write to root or Airtable, sign up for services | Through `gate` → owner approves on Telegram, or the action is dropped after a timeout |
| L4 Never | Email or message as the owner, spend money, touch credentials, delete outside the sandbox | Blocked: the sandbox has no credentials for these |

Every level is set per perennial in config. A perennial can be raised to allow L3 for one action class, for example "publish to its own GitHub Pages".

**Hard controls**

- **Separate macOS user** `perennial`. It has its own HOME, Keychain and Claude login, and a fine-grained GitHub token for a bot account. The owner's home is `chmod 700`, so dotfiles with secrets cannot be read.
- **Kill switch:** the file `~/.perennial/STOP`, `perennial stop`, or a STOP reply on Telegram through the gate. The supervisor checks before every tick and every run.
- **Budget:** a $/day cap and a $/run cap (`--max-budget-usd`). At most N concurrent runs.
- **Runaway guard:** a task that fails 3 times is parked. The same action repeated 5 times in one run ends the run.
- **Full log:** every run keeps its transcript (stream-json) in the workspace. The daily digest links to it.

## 5. Where todos come from (adapters)

| Adapter | Phase | Notes |
|---|---|---|
| Markdown checklist (`- [ ]`) in a file | 1 | Today.md and project TODO files. The host exports a snapshot into the sandbox. The perennial never writes to the vault; it writes its results to its own log. |
| GitHub issues with a label (e.g. `perennial`) | 1 | Via the bot account. The label is the opt-in. |
| Ideas inbox (its own `ideas.md`) | 2 | Written by the ideation run. |
| root pages (Juniper) | 3 | Read through the snapshot API. Write via the gate (L3). |
| Airtable `TO DO` table | 3 | Read-only snapshot. |

## 6. Phases

| Phase | Result | Plan |
|---|---|---|
| 1 Core runtime | One perennial runs under launchd. It reads Markdown and GitHub todos, triages them, does `do` tasks in workspaces, opens PRs and sends a daily digest. | `plans/2026-10-01-phase1-core-runtime.md` |
| 2 Ideas and builds | A nightly ideation run, scoring, and autonomous build of the top idea into a new bot-owned repo with a README and a demo. | written after phase 1 lands |
| 3 Many perennials + dashboard | Several named perennials with their own charters, a shared queue with claiming, a local dashboard, and root/Airtable adapters. | after phase 2 |
| 4 Always-on host | Move from the laptop to an always-on host (a Mac mini at the office or a cloud VM). Two-way chat through the existing Telegram receiver. | after phase 3 |

## 7. Known constraints

- **A laptop is not always on.** It sleeps, travels and has limited disk. Phase 1 uses `caffeinate` and launchd. Real 24/7 needs phase 4.
- **One Telegram poller per bot token.** Perennial must never poll Telegram. It sends through the existing `distress_call` CLI. Replies arrive through the existing receiver.
- **Claude subscription limits.** Heavy unattended use hits rate limits. The budget caps and the cheap triage model keep usage bounded.
