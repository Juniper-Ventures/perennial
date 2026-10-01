"""Read-only local status page: what the perennial is doing, what it spent, what it built."""
from __future__ import annotations

import html
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STYLE = (
    "body{font:14px/1.5 -apple-system,Helvetica,Arial,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;color:#111}"
    "table{border-collapse:collapse;width:100%;margin:8px 0 20px}td,th{border-bottom:1px solid #ddd;padding:5px 8px;"
    "text-align:left;vertical-align:top}th{background:#f4f4f4}.pill{display:inline-block;padding:1px 8px;border-radius:9px;"
    "background:#eee;margin-right:6px}h2{margin-top:28px}"
)


def e(v) -> str:
    return html.escape("" if v is None else str(v))


def _table(headers: list[str], rows: list[list]) -> str:
    if not rows:
        return "<p><i>none</i></p>"
    head = "".join(f"<th>{e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def render(store, cfg) -> str:
    stopped = cfg.stop_file.exists()
    counts = Counter(t["status"] for t in store.tasks())
    pills = "".join(f'<span class="pill">{e(k)}: {v}</span>' for k, v in sorted(counts.items()))
    runs = store.runs_since("0000")[-25:][::-1]
    tasks = [t for t in store.tasks() if t["status"] in ("ready", "running", "needs_human", "parked")]
    return (
        f"<!doctype html><html><head><meta charset=utf-8><meta http-equiv=refresh content=60>"
        f"<title>{e(cfg.name)} · perennial</title><style>{STYLE}</style></head><body>"
        f"<h1>{e(cfg.name)} — {'STOPPED' if stopped else 'running'}</h1>"
        f"<p>Spent today ${store.spent_today():.2f} of ${cfg.daily_budget_usd:.0f} · autonomy L{cfg.autonomy}</p>"
        f"<p>{pills}</p>"
        "<h2>Open tasks</h2>"
        + _table(["status", "title", "value", "effort", "why"],
                 [[t["status"], t["title"][:120], t["value"], t["effort"], (t["reason"] or "")[:160]] for t in tasks])
        + "<h2>Recent runs</h2>"
        + _table(["started", "ok", "cost", "task", "summary"],
                 [[r["started_at"], "yes" if r["ok"] else "no", f"${r['cost_usd']:.2f}", r["title"][:80],
                   (r["summary"] or "")[:240]] for r in runs])
        + "<h2>Ideas</h2>"
        + _table(["status", "title", "value", "effort", "novelty", "pitch"],
                 [[i["status"], i["title"], i["value"], i["effort"], i["novelty"], i["pitch"][:240]]
                  for i in store.ideas()[::-1][:30]])
        + "<h2>Approvals</h2>"
        + _table(["status", "action", "target", "created"],
                 [[a["status"], a["action"], a["payload"].get("repo", ""), a["created_at"]] for a in store.approvals()[::-1]])
        + "</body></html>"
    )


def serve(store_factory, cfg, port: int) -> None:
    """Serve the page on 127.0.0.1 only. GET / is the only route; there are no write endpoints."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/", "/index.html"):
                self.send_error(404)
                return
            body = render(store_factory(), cfg).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
