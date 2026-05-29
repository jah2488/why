#!/usr/bin/env python3
"""Render a markdown investigation report into a single self-contained HTML file.

The output embeds a vendored markdown renderer (assets/marked.min.js) and the raw
markdown source, so it renders fully offline, links are clickable, and the original
markdown can be copied out with one click.

Usage:
    render_report.py --markdown report.md --title "why: parseConfig" [--data report.data.json]
                     [--slug repo-symbol] [--output path.html]
    cat report.md | render_report.py --title "why: parseConfig"

--data points to an optional JSON sidecar describing structured facts (origin/recent,
events for the timeline, commits_by_month for the histogram, coupling list, project
metadata). When present, the renderer adds an "At a glance" card with chips + SVG
timeline + histogram + coupling above the prose. When absent, only the prose renders.

If --output is omitted, writes to ~/.claude/archaeology-reports/<slug>-<timestamp>.html
and prints the absolute path to stdout (the only thing printed to stdout).
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
TEMPLATE = ASSETS / "report_template.html"
MARKED = ASSETS / "marked.min.js"
HLJS = ASSETS / "highlight.min.js"
HLJS_LIGHT = ASSETS / "hljs-github-light.css"
HLJS_DARK = ASSETS / "hljs-github-dark.css"


def slugify(text: str) -> str:
    text = re.sub(r"[^\w.-]+", "-", text.strip().lower())
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "report"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--markdown", help="Path to the markdown report file. Reads stdin if omitted.")
    ap.add_argument("--title", default="why — code archaeology report", help="HTML page title.")
    ap.add_argument("--data", help="Optional JSON sidecar (see module docstring for fields).")
    ap.add_argument("--slug", help="Filename slug. Derived from --title if omitted.")
    ap.add_argument("--output", help="Explicit output path. Overrides the default location.")
    args = ap.parse_args()

    if args.markdown:
        markdown = Path(args.markdown).read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        markdown = sys.stdin.read()
    else:
        ap.error("provide --markdown FILE or pipe markdown via stdin")

    for asset in (TEMPLATE, MARKED):
        if not asset.exists():
            print(f"missing bundled asset: {asset}", file=sys.stderr)
            return 1

    template = TEMPLATE.read_text(encoding="utf-8")
    marked_js = MARKED.read_text(encoding="utf-8")
    hljs_js = HLJS.read_text(encoding="utf-8") if HLJS.exists() else ""
    hljs_light = HLJS_LIGHT.read_text(encoding="utf-8") if HLJS_LIGHT.exists() else ""
    hljs_dark = HLJS_DARK.read_text(encoding="utf-8") if HLJS_DARK.exists() else ""
    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    data_obj = None
    if args.data:
        try:
            data_obj = json.loads(Path(args.data).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"warning: ignoring --data ({e})", file=sys.stderr)

    # Defensively escape "</" inside any JSON payload that lands inside <script>,
    # so a stray "</script>" in markdown/data can't terminate the script tag.
    def js_safe(obj):
        return json.dumps(obj).replace("</", "<\\/")

    # Order matters: inject marked.js and the JSON payloads last so their contents
    # (which may themselves contain the placeholder tokens) are never re-substituted.
    html = template.replace("__TITLE__", args.title)
    html = html.replace("__GENERATED__", generated)
    html = html.replace("__HLJS_LIGHT_CSS__", hljs_light)
    html = html.replace("__HLJS_DARK_CSS__", hljs_dark)
    html = html.replace("__MARKED_JS__", marked_js)
    html = html.replace("__HLJS_JS__", hljs_js)
    html = html.replace("__MARKDOWN_JSON__", js_safe(markdown))
    html = html.replace("__DATA_JSON__", js_safe(data_obj))

    if args.output:
        out = Path(args.output).expanduser()
    else:
        slug = args.slug or slugify(args.title)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        out = Path.home() / ".claude" / "archaeology-reports" / f"{slug}-{stamp}.html"

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(str(out.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
