"""Juniper root workspace integration (host side; the API key never enters the sandbox).

- Inbox: a root page whose bullet items are todos for the perennials. Exported to a Markdown checklist.
- Results: the relay posts result pages under ONE fixed parent page, set by the owner on the relay command line.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

API = "https://root.juniper.xyz/api/ext/pages"
LI = re.compile(r"<li\b[^>]*>(.*?)</li>", re.S | re.I)
DONE_MARK = re.compile(r"^(✅|☑|\[x\])", re.I)


def html_items(content: str) -> list[str]:
    out = []
    for raw in LI.findall(content or ""):
        if re.search(r"<(s|del|strike)\b", raw, re.I):
            continue
        text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw)).split())
        if text and not DONE_MARK.match(text):
            out.append(text[:300])
    return out


def items_to_markdown(items: list[str], title: str) -> str:
    return f"# {title}\n" + "".join(f"- [ ] {i}\n" for i in items)


def _req(method: str, url: str, key: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"X-API-Key": key, "User-Agent": "perennial/0.1", "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def export_inbox(page_id: str, out: Path, key: str | None = None) -> int:
    key = key or os.environ["ROOT_API_KEY"]
    page = _req("GET", f"{API}?id={page_id}", key)["page"]
    items = html_items(page.get("content", ""))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(items_to_markdown(items, title=page.get("title", "root inbox")))
    tmp.rename(out)
    return len(items)


def markdown_to_html(md: str, title: str) -> str:
    if shutil.which("pandoc"):
        body = subprocess.run(["pandoc", "-f", "gfm", "-t", "html5"], input=md, capture_output=True, text=True,
                              timeout=60).stdout
    else:
        body = f"<pre>{html.escape(md)}</pre>"
    return (f"<!doctype html><html><head><meta charset=utf-8><title>{html.escape(title)}</title><style>"
            "body{font:15px/1.55 -apple-system,Helvetica,Arial,sans-serif;max-width:900px;margin:30px auto;padding:0 20px}"
            "pre,code{background:#f4f4f2;border-radius:3px}pre{padding:10px;overflow:auto}</style></head>"
            f"<body>{body}</body></html>")


def root_poster(parent_id: str, actor: str, key: str | None = None):
    """Return post(title, markdown) that creates a page under the fixed parent. The caller cannot pick the parent."""
    key = key or os.environ["ROOT_API_KEY"]

    def post(title: str, markdown: str) -> str:
        r = _req("POST", API, key, {"title": title[:150], "content": markdown_to_html(markdown, title),
                                    "icon": "🤖", "parent_id": parent_id, "actor": actor})
        return r.get("id", "")
    return post
