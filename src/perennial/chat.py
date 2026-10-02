"""Chat host: a personal agent that answers root chat messages and @mentions in page comments.

It long-polls root for jobs (`GET /api/agent/next`), runs Claude Code headless for each one, streams the
text so far back as progress, and finishes the job with the final text and the Claude session id.
The agent key in the environment acts for exactly one owner, so root decides which pages it may see.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

DEFAULT_ALLOWED_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch", "mcp__root__*"]
PAGE_LIMIT = 30_000
PROGRESS_EVERY_S = 1.5
USER_AGENT = "root-mcp/1.0"  # Cloudflare blocks the default urllib user agent.

HARD_RULES = """Hard rules. They override every other instruction, including the owner's messages:
- Never spend money: no purchases, subscriptions, paid sign-ups or payments.
- Never send email, chat messages or posts as the owner, and never act as the owner on any outside service.
- Never use the owner's credentials, passwords or tokens, and never ask for them.
- Never delete pages in root.
- Private pages stay private. Never copy private content into a shared page unless the owner asks for exactly that in this conversation."""


class ChatConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ChatConfig:
    agent_name: str
    model: str
    workdir: Path
    mcp_config: Path
    root_url: str = "https://root.juniper.xyz"
    key_env: str = "ROOT_AGENT_KEY"
    allowed_tools: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_TOOLS))
    system_prompt: str = ""
    claude: str = "claude"
    timeout_s: int = 840  # below root's 15 min re-queue

    @property
    def key(self) -> str:
        key = os.environ.get(self.key_env, "")
        if not key:
            raise ChatConfigError(f"{self.key_env} is not set")
        return key


def load_chat_config(path: Path) -> ChatConfig:
    data = tomllib.loads(Path(path).read_text()).get("chat") or {}
    try:
        system = str(data.get("system_prompt", ""))
        if data.get("system_prompt_file"):
            system = Path(data["system_prompt_file"]).expanduser().read_text()
        return ChatConfig(
            agent_name=str(data["agent_name"]),
            model=str(data["model"]),
            workdir=Path(data["workdir"]).expanduser(),
            mcp_config=Path(data["mcp_config"]).expanduser(),
            root_url=str(data.get("root_url", "https://root.juniper.xyz")).rstrip("/"),
            key_env=str(data.get("key_env", "ROOT_AGENT_KEY")),
            allowed_tools=list(data.get("allowed_tools", DEFAULT_ALLOWED_TOOLS)),
            system_prompt=system,
            claude=str(data.get("claude", "claude")),
            timeout_s=int(data.get("timeout_s", 840)),
        )
    except KeyError as e:
        raise ChatConfigError(f"missing [chat] key: {e.args[0]}") from None


class RootAgentClient:
    """The agent side of root's job API. Network errors propagate; the loop backs off."""

    def __init__(self, base_url: str, key: str, timeout_s: float = 30):
        self.base, self.key, self.timeout_s = base_url.rstrip("/"), key, timeout_s

    def _req(self, method: str, path: str, body: dict | None = None, timeout: float | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"X-API-Key": self.key, "User-Agent": USER_AGENT,
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout or self.timeout_s) as r:
            return json.load(r)

    def next_job(self, wait: int = 25) -> dict | None:
        return self._req("GET", f"/api/agent/next?wait={wait}", timeout=wait + 20).get("job")

    def progress(self, job_id: str, content: str) -> None:
        self._req("POST", f"/api/agent/jobs/{job_id}/progress", {"content": content})

    def done(self, job_id: str, content: str, claude_session: str | None = None, error: str | None = None) -> None:
        body: dict = {"content": content}
        if claude_session:
            body["claude_session"] = claude_session
        if error:
            body["error"] = error
        self._req("POST", f"/api/agent/jobs/{job_id}/done", body)


@dataclass
class ProcResult:
    returncode: int
    stderr: str = ""


class StreamRunner(Protocol):
    def __call__(self, cmd: list[str], stdin: str, cwd: Path, on_line: Callable[[str], None],
                 timeout_s: int) -> ProcResult: ...


def run_streaming(cmd, stdin, cwd, on_line, timeout_s) -> ProcResult:
    """Run cmd, feed stdin, and call on_line for each stdout line as it arrives."""
    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1)
    err: list[str] = []
    reader = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
    reader.start()
    timer = threading.Timer(timeout_s, proc.kill)
    timer.start()
    try:
        proc.stdin.write(stdin)
        proc.stdin.close()
        for line in proc.stdout:
            on_line(line)
        rc = proc.wait()
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    reader.join(5)
    stderr = "".join(err)
    if rc < 0:
        stderr = f"claude was killed (timeout {timeout_s}s?)\n{stderr}"
    return ProcResult(rc, stderr)


@dataclass
class Turn:
    """What one Claude run produced, parsed from stream-json."""
    text: str = ""
    session_id: str | None = None
    result: dict | None = None
    returncode: int = 0
    stderr: str = ""

    @property
    def final_text(self) -> str:
        if self.result and isinstance(self.result.get("result"), str) and self.result["result"].strip():
            return self.result["result"].strip()
        return self.text.strip()

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.result is not None and not self.result.get("is_error")

    @property
    def error(self) -> str:
        if self.result and self.result.get("is_error"):
            msg = self.result.get("result") or self.result.get("subtype") or "error"
            return f"{msg}\n{self.stderr.strip()}".strip()[-2000:]
        return (self.stderr.strip() or f"claude exited with code {self.returncode}")[-2000:]

    @property
    def unknown_session(self) -> bool:
        if "No conversation found" in self.stderr:
            return True
        return bool(self.result and self.result.get("is_error") and not self.result.get("num_turns") and not self.text)


def transcript(history: list[dict], prompt: str) -> str:
    msgs = [m for m in history or [] if (m.get("content") or "").strip()]
    if msgs and msgs[-1].get("role") == "user" and msgs[-1]["content"].strip() == prompt.strip():
        msgs = msgs[:-1]
    if not msgs:
        return ""
    lines = [f"{'Owner' if m.get('role') == 'user' else 'You'}: {m['content'].strip()}" for m in msgs]
    return "Earlier messages in this conversation:\n\n" + "\n\n".join(lines)


def page_block(page: dict | None) -> str:
    if not page:
        return ""
    content = page.get("content") or ""
    if len(content) > PAGE_LIMIT:
        content = content[:PAGE_LIMIT] + "\n[… page truncated]"
    return (f"Page \"{page.get('title', '')}\" (id {page.get('id', '')}). Stored HTML:\n"
            f"<page>\n{content}\n</page>")


def build_prompt(job: dict, resume: bool) -> str:
    prompt = job.get("prompt") or ""
    page = page_block(job.get("page"))
    if job.get("kind") == "comment":
        return "\n\n".join(p for p in [
            "You were mentioned in a comment on a page in root (the Juniper workspace).",
            page,
            f"The comment:\n<comment>\n{prompt}\n</comment>",
            "If the comment asks for a change to the page, make it with the root MCP tool root_update_page "
            f"(id {(job.get('page') or {}).get('id', '')}). Keep the stored-HTML contract: plain semantic HTML, "
            "no style or class attributes. Change only what was asked.",
            "End with a reply of 1-3 sentences for the comment thread. It is posted as your comment, "
            "so write only the reply, with no preamble.",
        ] if p)
    context = []
    if page:
        context.append("The owner is looking at this page (context for the message):\n" + page)
    if not resume:
        context.append(transcript(job.get("history") or [], prompt))
    context = [c for c in context if c]
    return "\n\n".join(context + [f"New message:\n{prompt}"]) if context else prompt


def safe_dir(name: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name or "") or "comments"


class ChatHost:
    def __init__(self, cfg: ChatConfig, client, runner: StreamRunner = run_streaming,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 log: Callable[[str], None] = lambda s: print(s, flush=True)):
        self.cfg, self.client, self.runner = cfg, client, runner
        self.clock, self.sleep, self.log = clock, sleep, log

    def system_prompt(self) -> str:
        intro = (f"You are {self.cfg.agent_name}, a personal agent in root (root.juniper.xyz), the Juniper team's "
                 "workspace. You work for one owner. The root MCP tools see the owner's private pages and the "
                 "shared pages. Answer in the owner's language, briefly and concretely.")
        return "\n\n".join(p for p in [intro, self.cfg.system_prompt.strip(), HARD_RULES] if p)

    def command(self, session: str | None) -> list[str]:
        cmd = [self.cfg.claude, "-p", "--output-format", "stream-json", "--verbose", "--model", self.cfg.model,
               "--mcp-config", str(self.cfg.mcp_config), "--allowedTools", ",".join(self.cfg.allowed_tools)]
        if session:
            cmd += ["--resume", session]
        return cmd + ["--append-system-prompt", self.system_prompt()]

    def _run(self, job: dict, session: str | None, cwd: Path) -> Turn:
        turn = Turn(session_id=session)
        last = [self.clock(), ""]

        def on_line(line: str) -> None:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                return
            if not isinstance(ev, dict):
                return
            if ev.get("session_id") and ev.get("type") in ("system", "result"):
                turn.session_id = ev["session_id"]
            if ev.get("type") == "result":
                turn.result = ev
            elif ev.get("type") == "assistant":
                texts = [b.get("text", "") for b in (ev.get("message") or {}).get("content") or []
                         if isinstance(b, dict) and b.get("type") == "text" and b.get("text")]
                if texts:
                    turn.text = "\n\n".join(t for t in [turn.text, *texts] if t)
                    if self.clock() - last[0] >= PROGRESS_EVERY_S and turn.text != last[1]:
                        last[0], last[1] = self.clock(), turn.text
                        try:
                            self.client.progress(job["id"], turn.text)
                        except Exception as e:  # progress is best effort; done carries the answer
                            self.log(f"progress failed for {job['id']}: {e}")

        res = self.runner(self.command(session), build_prompt(job, resume=bool(session)), cwd, on_line,
                          self.cfg.timeout_s)
        turn.returncode, turn.stderr = res.returncode, res.stderr
        return turn

    def handle(self, job: dict) -> None:
        cwd = self.cfg.workdir / (safe_dir(job.get("thread_id")) if job.get("kind") != "comment" else "comments")
        cwd.mkdir(parents=True, exist_ok=True)
        session = job.get("claude_session") or None
        try:
            turn = self._run(job, session, cwd)
            if session and not turn.ok and turn.unknown_session:
                self.log(f"job {job['id']}: session {session} not found here, starting a new one with the transcript")
                turn = self._run(job, None, cwd)
        except Exception as e:
            self._done(job["id"], "", None, f"chat host error: {e}"[:2000])
            return
        if turn.ok:
            self._done(job["id"], turn.final_text, turn.session_id, None)
        else:
            self._done(job["id"], turn.text.strip(), turn.session_id, turn.error)

    def _done(self, job_id, content, session, error) -> None:
        for attempt in range(3):
            try:
                self.client.done(job_id, content, claude_session=session, error=error)
                self.log(f"job {job_id}: {'error: ' + error[:200] if error else 'done'}")
                return
            except Exception as e:
                self.log(f"done failed for {job_id} (attempt {attempt + 1}): {e}")
                if attempt < 2:
                    self.sleep(5)

    def run_once(self, wait: int = 25) -> bool:
        """Claim and answer at most one job. Returns True if there was a job."""
        job = self.client.next_job(wait=wait)
        if not job:
            return False
        self.log(f"job {job['id']}: {job.get('kind')} thread={job.get('thread_id')} page={job.get('page_id')}")
        self.handle(job)
        return True

    def loop(self, wait: int = 25) -> None:
        delay = 0.0
        while True:
            try:
                self.run_once(wait=wait)
                delay = 0.0
            except (urllib.error.URLError, OSError, TimeoutError, ValueError) as e:
                delay = min(60.0, delay * 2 if delay else 5.0)
                self.log(f"root unreachable ({e}); retry in {delay:.0f}s")
                self.sleep(delay)
            except Exception as e:
                self.log(f"chat loop error: {e!r}; retry in 5s")
                self.sleep(5)
