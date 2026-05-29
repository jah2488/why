#!/usr/bin/env python3
"""Rank git authors who have shaped a file the most.

Counts every commit touching the file once for its primary author, plus once for each
`Co-authored-by:` trailer in the commit message — so pair-programmed and reviewed-in commits
get correct attribution. Tracks the most recent contribution date per person.

Usage:
    find_authors.py --file <path> [--repo .] [--lines <start>,<end>]
                    [--limit 800] [--top 10] [--json]

`--lines` scopes the scan to commits that touched a specific line range (via `git log -L`,
which follows the range through history). Use it when investigating a method or block —
otherwise the result reflects the *whole file's* authors, which is misleading for narrow
targets in large files.

Output is human-readable text by default (or `--json`). Each row carries a gravatar URL
(MD5 of the email, the standard gravatar identifier) the renderer can drop in directly.

Python 3.9; stdlib only.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_urls import parse_lines_arg  # noqa: E402


SEP = "__C__"
END = "__E__"
COAUTHOR_RE = re.compile(r"^Co-authored-by:\s*(.+?)\s*<(.+?)>\s*$", re.M | re.I)


def gravatar(email: str) -> str:
    h = hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()
    return f"https://www.gravatar.com/avatar/{h}?s=72&d=identicon"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True, help="Path to the target file (repo-relative or absolute).")
    ap.add_argument("--repo", default=".", help="Repo working dir (default: cwd).")
    ap.add_argument("--lines", type=parse_lines_arg,
                    help="Optional line range 'start,end' — scopes the scan to commits that "
                         "affected those lines (via `git log -L`, follows the range through history). "
                         "Use this for method-level investigations to avoid file-wide author noise.")
    ap.add_argument("--limit", type=int, default=800, help="Max touching-commits to scan (default 800).")
    ap.add_argument("--top", type=int, default=10, help="How many authors to report (default 10).")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    target = args.file
    tp = Path(target)
    if tp.is_absolute():
        try:
            target = str(tp.resolve().relative_to(repo))
        except ValueError:
            pass

    # Single git pass: per commit emit author/email/date and the full body.
    fmt = f"{SEP}%n%H%n%an%n%ae%n%cI%n%B%n{END}"
    if args.lines:
        start, end = args.lines
        # `-L` scopes to the line range and follows it through history. `-s` (`--no-patch`)
        # suppresses the diff so we only get the metadata our format string asks for.
        # `-L` syntax embeds the path; can't combine with `--` or `--follow`.
        raw = subprocess.run(
            ["git", "-C", str(repo), "log", f"-n{args.limit}", "-s", f"--format={fmt}",
             f"-L{start},{end}:{target}"],
            capture_output=True, text=True).stdout
    else:
        raw = subprocess.run(
            ["git", "-C", str(repo), "log", f"-n{args.limit}", "--follow", f"--format={fmt}", "--", target],
            capture_output=True, text=True).stdout

    people = defaultdict(lambda: {"name": "", "email": "", "commits": 0, "last": ""})
    blocks = raw.split(SEP)
    for block in blocks:
        if not block.strip():
            continue
        lines = block.lstrip("\n").split("\n")
        try:
            sha = lines[0]
            name = lines[1]
            email = lines[2]
            date = lines[3]
        except IndexError:
            continue
        # body is everything between lines[4] and the line == END
        body_lines = []
        for ln in lines[4:]:
            if ln == END:
                break
            body_lines.append(ln)
        body = "\n".join(body_lines)

        key = (email or name).strip().lower()
        if key:
            p = people[key]
            if not p["name"]:
                p["name"] = name
                p["email"] = email
            p["commits"] += 1
            if not p["last"] or date > p["last"]:
                p["last"] = date

        for m in COAUTHOR_RE.finditer(body):
            co_name, co_email = m.group(1), m.group(2)
            ckey = co_email.strip().lower() or co_name.strip().lower()
            if not ckey:
                continue
            cp = people[ckey]
            if not cp["name"]:
                cp["name"] = co_name
                cp["email"] = co_email
            cp["commits"] += 1
            if not cp["last"] or date > cp["last"]:
                cp["last"] = date

    # Two-pass stable sort: primary key (commits desc), secondary key (last date desc).
    ranked = sorted(people.values(), key=lambda p: p["last"], reverse=True)
    ranked.sort(key=lambda p: p["commits"], reverse=True)
    ranked = ranked[:args.top]

    for p in ranked:
        if p["email"]:
            p["avatar_url"] = gravatar(p["email"])

    if args.json:
        print(json.dumps({"file": target, "authors": ranked}, indent=2))
        return

    if not ranked:
        print(f"No authors found for {target}.")
        return
    print(f"Frequent authors of {target} (scanned {sum(p['commits'] for p in ranked)} attributions):\n")
    for p in ranked:
        last = p["last"][:10] if p["last"] else "—"
        print(f"  {p['commits']:>4}  {p['name']:<28}  {p['email']:<40}  last {last}")


if __name__ == "__main__":
    main()
