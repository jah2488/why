#!/usr/bin/env python3
"""Emit the `commits_by_month` histogram JSON the renderer expects.

Counts the number of touching commits per calendar month, optionally scoped to a line range.
Returns `{"YYYY-MM": N, ...}` shape directly — no shell reshaping needed.

Usage:
    commits_by_month.py --file <path> [--repo .] [--lines start,end]

Scope:
    Without `--lines`: counts commits that touched the file (across renames, via `--follow`).
    With `--lines start,end`: counts commits that affected those lines (via `-L`), following
    the range through history.

Python 3.9; stdlib only.
"""
import argparse
import collections
import json
import re
import subprocess
from pathlib import Path


def parse_lines(s):
    if not s:
        return None
    m = re.match(r"^(\d+)\s*,\s*(\d+)$", s.strip())
    if not m:
        raise argparse.ArgumentTypeError("expected --lines as 'start,end'")
    a, b = int(m.group(1)), int(m.group(2))
    return (min(a, b), max(a, b))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--lines", type=parse_lines,
                    help="Optional line range 'start,end' to scope the histogram.")
    args = ap.parse_args()
    repo = Path(args.repo).expanduser().resolve()

    target = args.file
    tp = Path(target)
    if tp.is_absolute():
        try:
            target = str(tp.resolve().relative_to(repo))
        except ValueError:
            pass

    if args.lines:
        start, end = args.lines
        out = subprocess.run(
            ["git", "-C", str(repo), "log", "-s",
             "--format=%ad", "--date=format:%Y-%m",
             f"-L{start},{end}:{target}"],
            capture_output=True, text=True,
        ).stdout
    else:
        out = subprocess.run(
            ["git", "-C", str(repo), "log", "--follow",
             "--format=%ad", "--date=format:%Y-%m", "--", target],
            capture_output=True, text=True,
        ).stdout

    counts = collections.Counter(line.strip() for line in out.splitlines() if line.strip())
    # Sort by month key for stable output (renderer doesn't require it but it reads better).
    print(json.dumps(dict(sorted(counts.items())), indent=2))


if __name__ == "__main__":
    main()
