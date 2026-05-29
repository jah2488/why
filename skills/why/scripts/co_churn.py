#!/usr/bin/env python3
"""Temporal coupling ("code-morbidity") for a file.

When a piece of code has been changed across several PRs, the files that keep
changing *in the same commits* are very likely coupled — they probably need to be
changed together. This surfaces that hidden association so an editor knows what
else to look at.

Algorithm: collect the commits that touched the target file (following renames),
then for each, list ALL files in that commit (`git diff-tree`, NOT pathspec-filtered
— a pathspec filter would hide the very files we're looking for), and tally how
often each other file co-changed with the target.

Usage:
    co_churn.py --file app/models/user.rb [--repo ~/Projects/foo] [--lines <start>,<end>]
                [--limit 300] [--min-commits 3] [--top 12] [--json]

`--lines` scopes the analysis to commits that affected a specific line range (via
`git log -L`). Use it when investigating a method or block — file-wide co-churn on a
large file mostly surfaces incidental neighbours; line-scoped co-churn surfaces files
that *actually* travel with the code you care about.

Exit/Output:
    Prints a human-readable summary. If the (line-scoped or file-wide) target has fewer
    than --min-commits touching commits, prints a "low churn" note and the skill should
    rely on the origin/recent-change story instead.
Python 3.9 compatible; stdlib only.
"""
import argparse
import collections
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_urls import parse_remote, default_branch, blob_url, commit_url, parse_lines_arg  # noqa: E402


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True).stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True, help="Path to the target file (repo-relative or absolute).")
    ap.add_argument("--repo", default=".", help="Repo working dir (default: cwd).")
    ap.add_argument("--lines", type=parse_lines_arg,
                    help="Optional line range 'start,end' — scopes co-churn to commits that "
                         "affected those lines. Strongly recommended for method-level investigations.")
    ap.add_argument("--limit", type=int, default=300, help="Max touching-commits to analyze (default 300).")
    ap.add_argument("--min-commits", type=int, default=3, help="Below this, skip co-churn as low-signal.")
    ap.add_argument("--top", type=int, default=12, help="How many coupled files to show.")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    target = args.file
    # Normalize an absolute path to repo-relative so it matches diff-tree output.
    tp = Path(target)
    if tp.is_absolute():
        try:
            target = str(tp.resolve().relative_to(repo))
        except ValueError:
            pass

    if args.lines:
        start, end = args.lines
        # `-L` scopes to the line range and follows it through history; `-s` (no-patch)
        # leaves us with just the SHA lines our format asks for. `-L` syntax embeds the
        # path, so we can't combine with `--` or `--follow`.
        shas = [s for s in git(repo, "log", f"-n{args.limit}", "-s", "--format=%H",
                                f"-L{start},{end}:{target}").split() if s]
    else:
        shas = [s for s in git(repo, "log", f"-n{args.limit}", "--format=%H",
                                "--follow", "--", target).split() if s]
    total = len(shas)

    if total < args.min_commits:
        msg = (f"Target '{target}' has only {total} touching-commit(s) "
               f"(< {args.min_commits}). Co-churn is low-signal here — the origin "
               f"and any single significant change explain it; skip the coupling section.")
        print(json.dumps({"target": target, "touching_commits": total, "skipped": True, "reason": msg})
              if args.json else "LOW CHURN: " + msg)
        return

    co = collections.Counter()
    shared = collections.defaultdict(list)  # file -> sample short shas co-changed with target
    analyzed = 0
    for sha in shas:
        files = set(git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).split())
        if not files:
            continue  # merge commit or empty; skip
        analyzed += 1
        for f in files:
            if f != target:
                co[f] += 1
                if len(shared[f]) < 4:
                    shared[f].append(sha[:9])

    remote = parse_remote(repo)
    branch = default_branch(repo)
    ranked = co.most_common(args.top)
    rows = [{
        "file": f,
        "url": blob_url(remote, branch, f),
        "co_changes": ct,
        "pct_of_target_commits": round(100 * ct / max(analyzed, 1)),
        "sample_shared_commits": [
            {"sha": s, "url": commit_url(remote, s)} for s in shared[f]
        ],
    } for f, ct in ranked]

    if args.json:
        print(json.dumps({"target": target, "touching_commits": total,
                          "analyzed_commits": analyzed, "coupled_files": rows}, indent=2))
        return

    print(f"CO-CHURN for {target}")
    print(f"  touched by {total} commits (analyzed {analyzed} non-merge); top coupling:\n")
    print(f"  {'co':>4} {'%':>4}  file (sample shared commits)")
    for r in rows:
        sample = ", ".join(s["sha"] if isinstance(s, dict) else s
                           for s in r["sample_shared_commits"])
        print(f"  {r['co_changes']:>4} {r['pct_of_target_commits']:>3}%  "
              f"{r['file']}  [{sample}]")
    print("\n  Interpretation: files high on this list likely must change together with the\n"
          "  target. For the strongest couplings, open one shared commit/PR to learn WHY.")


if __name__ == "__main__":
    main()
