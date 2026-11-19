#!/usr/bin/env python3
"""Mirror relevant open upstream issues and PRs into this fork as tracking issues.

This deliberately mirrors metadata and links only. It never imports code, creates branches,
opens code PRs, or merges upstream changes.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

UPSTREAM = os.environ.get("UPSTREAM_REPOSITORY", "HarnessRouter/harnessrouter")
TARGET = os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ["GH_TOKEN"]
API = "https://api.github.com"
MARKER_RE = re.compile(r"<!-- upstream-sync: ([^#]+)#(\d+) (issue|pr) -->")
RELEVANT = re.compile(
    r"\b(harness|router|runner|resume|workspace|lease|fencing|idempotenc\w*|"
    r"protocol|uhp|backend|agent|security|egress|sandbox|session|checkpoint|"
    r"benchmark|memory|graphiti|provider|mcp|install|chromium|playwright|"
    r"recover\w*|reconcil\w*|governance|cve|pi lab|sync.from.source|"
    r"plugin|auth|persistent runtime|deployment|self.host)\b",
    re.IGNORECASE,
)

def request(method: str, path: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"GitHub API {method} {path}: HTTP {exc.code}: {detail[:1000]}") from exc

def all_pages(path: str) -> list[dict]:
    result = []
    page = 1
    while True:
        batch = request("GET", f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
        if not isinstance(batch, list):
            raise RuntimeError(f"Expected list from {path}")
        result.extend(batch)
        if len(batch) < 100:
            return result
        page += 1

def relevant(item: dict) -> bool:
    labels = " ".join(x.get("name", "") for x in item.get("labels", []))
    text = f"{item.get('title', '')}\n{item.get('body') or ''}\n{labels}"
    return bool(RELEVANT.search(text))

def source_kind(item: dict) -> str:
    return "pr" if item.get("_kind") == "pr" or "pull_request" in item else "issue"

def marker(item: dict) -> str:
    return f"<!-- upstream-sync: {UPSTREAM}#{item['number']} {source_kind(item)} -->"

def render(item: dict) -> tuple[str, str]:
    kind = source_kind(item)
    label = "PR" if kind == "pr" else "ISSUE"
    title = f"[UPSTREAM {label} #{item['number']}] {item['title']}"
    labels = ", ".join(x.get("name", "") for x in item.get("labels", [])) or "(none)"
    original = (item.get("body") or "_No description supplied upstream._").strip()
    if len(original) > 12000:
        original = original[:12000] + "\n\n_(truncated by the mirror; see the upstream source for the full text.)_"
    body = f"""{marker(item)}
**Upstream source:** {UPSTREAM}  
**Type:** {label}  
**Status upstream:** {item.get('state', 'unknown')}  
**Updated upstream:** {item.get('updated_at', 'unknown')}  
**Labels upstream:** {labels}

**Original:** {item.get('html_url', '')}

---

## Upstream description

{original}

---

This is an automatically maintained tracking mirror. Discuss and review the canonical item upstream.
For upstream PRs, this issue tracks the proposal/change; it does **not** import its code into this fork.
"""
    return title, body

def main() -> int:
    repository = request("GET", f"/repos/{TARGET}")
    if not repository.get("has_issues", False):
        print(json.dumps({
            "upstream": UPSTREAM,
            "target": TARGET,
            "blocked": "GitHub Issues is disabled for this repository. Enable Settings > General > Features > Issues to activate the mirror.",
        }, indent=2))
        return 0

    upstream_issues = [
        item for item in all_pages(f"/repos/{UPSTREAM}/issues?state=all")
        if "pull_request" not in item
    ]
    upstream_prs = all_pages(f"/repos/{UPSTREAM}/pulls?state=all")
    for item in upstream_prs:
        item["_kind"] = "pr"
    sources = upstream_issues + upstream_prs

    local = all_pages(f"/repos/{TARGET}/issues?state=all")
    mirrors = {}
    for issue in local:
        if "pull_request" in issue:
            continue
        match = MARKER_RE.search(issue.get("body") or "")
        if match and match.group(1) == UPSTREAM:
            mirrors[(match.group(3), int(match.group(2)))] = issue

    created = updated = closed = skipped = 0
    for item in sorted(sources, key=lambda x: (x.get("updated_at") or "", x["number"])):
        kind = source_kind(item)
        key = (kind, int(item["number"]))
        existing = mirrors.get(key)
        if not relevant(item):
            skipped += 1
            continue
        if item.get("state") != "open" and existing is None:
            skipped += 1
            continue

        title, body = render(item)
        if existing is None:
            made = request("POST", f"/repos/{TARGET}/issues", {
                "title": title, "body": body,
            })
            mirrors[key] = made
            created += 1
            continue

        changes = {}
        if existing.get("title") != title:
            changes["title"] = title
        if existing.get("body") != body:
            changes["body"] = body
        desired_state = "open" if item.get("state") == "open" else "closed"
        if existing.get("state") != desired_state:
            changes["state"] = desired_state
        if changes:
            request("PATCH", f"/repos/{TARGET}/issues/{existing['number']}", changes)
            if desired_state == "closed":
                closed += 1
            else:
                updated += 1

    print(json.dumps({
        "upstream": UPSTREAM,
        "target": TARGET,
        "source_items_seen": len(sources),
        "created": created,
        "updated": updated,
        "closed": closed,
        "skipped_not_relevant_or_closed": skipped,
        "mirrors_found": len(mirrors),
    }, indent=2))
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"upstream sync failed: {exc}", file=sys.stderr)
        raise
