#!/usr/bin/env python3
"""Generate the TopicFinder working user-story catalog from Linear + QA verdicts.

CANONICAL LOCATION: octo-lite/workflows/lib/build-story-catalog.py (version
controlled). /root/codex-uploads/build-story-catalog.py is a SYMLINK to this
file — edit here, not there. It reads QA artifacts from /root/codex-uploads.

One generator, two destinations (never hand-edited, cannot drift):
- Notion page under Product -> Dev Section (business agents)
- Markdown for the Turbo repo's spec/ dir (dev agents)

Scope: QA-PROVEN stories only (verdict satisfied=true in
/root/codex-uploads/qa-verdicts/<ISSUE>.json), organized by app surface.
Only real Linear keys (TUR-\\d+) with a rendered verdict are included; junk
verdicts (accepted.json, INTEGRATION-*, satisfied:null) are skipped. Issues
with partial evidence are listed in a short "being backfilled" note.

Tolerates AC-schema drift across QA-loop versions: the per-AC label may live
under 'criterion', 'text', or an 'ac' index; a missing 'status' counts as
not-pass.

Run as part of the post-acceptance merge routine, after the QA verdict is
written:  python3 /root/codex-uploads/build-story-catalog.py [--publish-notion]

DRIFT HISTORY: on 2026-07-04 this had silently stopped working — the QA loop's
newer verdict schema crashed it (KeyError 'criterion'), so both destinations
froze at a 2026-07-03 snapshot (4 proven) while ~24 proven verdicts piled up
unpublished. The merge routine MUST stop-and-surface if this errors.
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

UPLOADS = Path("/root/codex-uploads")
VERDICTS = UPLOADS / "qa-verdicts"
CACHE_FILE = UPLOADS / ".issue-cache.json"
OUT_MD = UPLOADS / "story-catalog.md"
NOTION_STATE = UPLOADS / ".story-catalog-notion.json"
NOTION_PARENT = "page:1196e88b1e6482caa8cb815f150df2f7"  # Product -> Dev Section
EVIDENCE_BASE = "http://147.182.226.89:8080"
LINEAR_BASE = "https://linear.app/martellventures/issue"

SURFACES = ["Onboarding", "Discover", "Create & Remix", "Shoot & Scripts",
            "App Shell, Settings & Admin", "Golden Path (end-to-end)"]
SURFACE_MAP = {  # explicit issue -> surface; keyword fallback below
    "TUR-49": "Discover", "TUR-50": "Golden Path (end-to-end)",
    "TUR-58": "Onboarding", "TUR-60": "Shoot & Scripts", "TUR-62": "Onboarding",
    "TUR-70": "Discover", "TUR-81": "App Shell, Settings & Admin",
}
KEYWORDS = [("onboard", "Onboarding"), ("scan", "Onboarding"),
            ("discover", "Discover"), ("swipe", "Discover"),
            ("remix", "Create & Remix"), ("script-gen", "Create & Remix"),
            ("voice", "Create & Remix"), ("folder", "Shoot & Scripts"),
            ("library", "Shoot & Scripts"), ("shoot", "Shoot & Scripts"),
            ("sidebar", "App Shell, Settings & Admin"),
            ("settings", "App Shell, Settings & Admin"),
            ("admin", "App Shell, Settings & Admin")]


def surface_for(key: str, title: str) -> str:
    if key in SURFACE_MAP:
        return SURFACE_MAP[key]
    t = title.lower()
    for kw, s in KEYWORDS:
        if kw in t:
            return s
    return "App Shell, Settings & Admin"


def short(text: str, n: int = 110) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


def ac_text(r: dict) -> str:
    """AC label across verdict-schema variants (criterion / text / ac-index)."""
    return (r.get("criterion") or r.get("text")
            or (f"AC{r['ac']}" if r.get("ac") is not None else "")).strip()


def is_pass(r: dict) -> bool:
    return r.get("status") == "pass"


def story_map_for(key: str):
    """(story-map entries, artifacts dir name) for an issue, or ([], None)."""
    num = key.split("-")[1]
    for d in UPLOADS.iterdir():
        if d.is_dir() and re.search(rf"tur-?{num}(?!\d)", d.name, re.I):
            smf = d / "story-map.json"
            if smf.exists():
                try:
                    return json.loads(smf.read_text()), d.name
                except Exception:
                    pass
    return [], None


def main() -> None:
    issue_meta = {}
    if CACHE_FILE.exists():
        issue_meta = json.loads(CACHE_FILE.read_text()).get("issues", {})

    proven, partial = [], []
    for p in sorted(VERDICTS.glob("*.json"), key=lambda p: p.stem):
        v = json.loads(p.read_text())
        key = v.get("issue") or p.stem
        # Only real Linear stories with a rendered verdict. Skips junk
        # (accepted.json), non-story integration passes (INTEGRATION-tur50-*),
        # and issues QA left unrendered (satisfied is null).
        if not re.match(r"TUR-\d+$", key) or v.get("satisfied") is None:
            continue
        info = issue_meta.get(key, {})
        entry = {
            "key": key,
            "title": info.get("title", ""),
            "url": info.get("url", f"{LINEAR_BASE}/{key}"),
            "story": v.get("user_story", ""),
            "verdict": v,
        }
        (proven if v.get("satisfied") else partial).append(entry)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# TopicFinder — Working User Stories",
        "",
        f"> **Generated {now}** from Linear user stories + independent QA verdicts "
        f"(visual evidence graded per acceptance criterion). **Do not edit here** — "
        f"stories live in Linear; proof lives on the [QA evidence site]({EVIDENCE_BASE}). "
        f"Backend/test criteria are validated at merge (tests + code review), not by video.",
        "",
        f"**{len(proven)} proven** · {len(partial)} more being evidence-backfilled",
        "",
    ]

    by_surface: dict[str, list] = {}
    for e in proven:
        by_surface.setdefault(surface_for(e["key"], e["title"]), []).append(e)

    for surface in SURFACES:
        entries = by_surface.get(surface)
        if not entries:
            continue
        lines.append(f"## {surface}")
        lines.append("")
        for e in entries:
            v = e["verdict"]
            passing = [r for r in v.get("ac_results", []) if is_pass(r)]
            unproven = [r for r in v.get("ac_results", []) if not is_pass(r)]
            lines.append(f"### {e['title'] or e['key']}")
            lines.append("")
            if e["story"]:
                lines.append(f"*{short(e['story'], 300)}*")
                lines.append("")
            sm, sm_dir = story_map_for(e["key"])
            if sm:
                lines.append("Proven user stories (each with its video evidence):")
                for entry in sm:
                    links = " · ".join(f"[▶ video]({EVIDENCE_BASE}/{sm_dir}/{p})"
                                       for p in entry.get("videos", []))
                    lines.append(f"- {entry['story']} {links}")
                lines.append("")
                lines.append("<details><summary>Acceptance criteria detail</summary>")
                lines.append("")
                for r in passing:
                    lines.append(f"- ✓ {short(ac_text(r))}")
                if unproven:
                    lines.append(f"- _(+{len(unproven)} backend/test criteria validated at merge)_")
                lines.append("")
                lines.append("</details>")
            elif passing:
                lines.append("What's proven working:")
                for r in passing:
                    lines.append(f"- {short(ac_text(r))}")
                if unproven:
                    lines.append(f"- _(+{len(unproven)} backend/test criteria validated at merge, "
                                 f"not visually evidenced)_")
            else:
                lines.append("Shipped and QA-accepted — see the evidence link below.")
            lines.append("")
            lines.append(f"[{e['key']} on Linear]({e['url']}) · "
                         f"[evidence]({EVIDENCE_BASE}/#{e['key']})")
            lines.append("")

    if partial:
        lines.append("## Being backfilled (shipped, evidence gaps queued for re-capture)")
        lines.append("")
        for e in partial:
            st = {"pass": 0, "fail": 0, "not_evidenced": 0}
            for r in e["verdict"].get("ac_results", []):
                # tolerate improvised/missing statuses (e.g. "partial") as not-pass
                status = r.get("status")
                st[status if status in st else "not_evidenced"] += 1
            lines.append(f"- **[{e['key']}]({e['url']})** {short(e['title'], 80)} — "
                         f"{st['pass']} AC proven, {st['fail'] + st['not_evidenced']} pending "
                         f"([evidence]({EVIDENCE_BASE}/#{e['key']}))")
        lines.append("")

    # rstrip every line (story-map source text and empty link slots can leave
    # trailing spaces) + single trailing newline, so the repo twin passes the
    # `git diff --check` PR gate.
    md = "\n".join(line.rstrip() for line in lines).rstrip("\n") + "\n"
    OUT_MD.write_text(md)
    print(f"wrote {OUT_MD} ({len(proven)} proven, {len(partial)} partial)")

    if "--publish-notion" in sys.argv:
        state = json.loads(NOTION_STATE.read_text()) if NOTION_STATE.exists() else {}
        page_id = state.get("page_id")
        if page_id:
            # content via stdin (ntn reads stdin when --content is omitted):
            # the catalog is >128KB and growing, and a single argv element
            # that large blows the kernel's per-arg execve limit (Errno 7).
            r = subprocess.run(["ntn", "pages", "edit", page_id],
                               input=md, capture_output=True, text=True)
            print("notion edit:", (r.stdout or r.stderr).strip()[:200])
            if r.returncode != 0:
                print(r.stderr, file=sys.stderr)
                sys.exit(1)
        else:
            r = subprocess.run(["ntn", "pages", "create", "--parent", NOTION_PARENT],
                               input=md, capture_output=True, text=True)
            out = (r.stdout or "") + (r.stderr or "")
            print("notion create:", out.strip()[:300])
            if r.returncode != 0:
                print(r.stderr, file=sys.stderr)
                sys.exit(1)
            m = re.search(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}", out)
            if m:
                NOTION_STATE.write_text(json.dumps({"page_id": m.group(0)}))
                print("saved page id:", m.group(0))


if __name__ == "__main__":
    main()
