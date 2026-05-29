#!/usr/bin/env python3
"""Find revert pairs in a file's history (or a line range within a file).

This is a **best-effort signal**, not a definitive answer. It catches the easy cases — commits
whose subject starts with "Revert" or whose body carries the standard `This reverts commit
<sha>` trailer — and tries to spot whether the reverted change was later re-applied. The
re-application heuristic uses word-overlap with the original subject; if the re-application
landed under a different title (very common), the script will say "no obvious re-application
found" even when one exists. **Always eyeball the surrounding history yourself when deciding
whether a constraint reflects current behavior.**

Detects:
  EXPLICIT — a commit whose subject starts with "Revert" or whose body contains the
             standard "This reverts commit <sha>" trailer that `git revert` writes.
  RE-APPLIED — when a reverted commit's subject keywords reappear in a later commit. Soft
               signal; verify by hand.

Usage:
    find_reverts.py --file <path> [--repo .] [--lines <start>,<end>]
                    [--limit 800] [--json]

`--lines start,end` scopes the scan to commits that touched a specific line range — useful
when you're investigating a method or block inside a large file where file-wide reverts are
mostly noise. Without `--lines`, all touching commits are scanned.

Output is human-readable text by default (or `--json`). JSON entries include `sha_url`,
`reverted_sha_url`, and `readded_sha_url` pre-built from the repo's GitHub remote, so the
skill can drop them into the sidecar without templating URLs.

Python 3.9; stdlib only.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_urls import parse_remote, commit_url  # noqa: E402


SEP = "__C__"
END = "__E__"
COAUTHOR_RE = re.compile(r"^Co-authored-by:\s*(.+?)\s*<(.+?)>\s*$", re.M | re.I)
REVERTS_SHA_RE = re.compile(r"This reverts commit ([0-9a-f]{7,40})", re.I)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True).stdout


def parse_lines_arg(s):
    if not s:
        return None
    m = re.match(r"^(\d+)\s*,\s*(\d+)$", s.strip())
    if not m:
        raise argparse.ArgumentTypeError("expected --lines as 'start,end' (e.g. 459,472)")
    a, b = int(m.group(1)), int(m.group(2))
    if a > b:
        a, b = b, a
    return (a, b)


def collect_commits(repo, target, lines, limit):
    """Return list of {sha, subject, body} for commits touching the target (and line range)."""
    fmt = f"{SEP}%n%H%n%s%n%b%n{END}"
    if lines:
        start, end = lines
        # `-L` scopes to commits affecting the line range, following them through history.
        # `-s` (`--no-patch`) suppresses the diff; `--format` controls the metadata.
        raw = git(repo, "log", f"-n{limit}", "-s", f"--format={fmt}",
                  f"-L{start},{end}:{target}")
    else:
        raw = git(repo, "log", f"-n{limit}", "--follow", f"--format={fmt}",
                  "--", target)
    commits = []
    lines_split = raw.split("\n")
    i = 0
    while i < len(lines_split):
        if lines_split[i] == SEP:
            i += 1
            sha = lines_split[i] if i < len(lines_split) else ""
            i += 1
            subject = lines_split[i] if i < len(lines_split) else ""
            i += 1
            body_lines = []
            while i < len(lines_split) and lines_split[i] != END:
                body_lines.append(lines_split[i])
                i += 1
            commits.append({"sha": sha, "subject": subject, "body": "\n".join(body_lines)})
            i += 1
        else:
            i += 1
    return commits


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True, help="Path to the target file (repo-relative or absolute).")
    ap.add_argument("--repo", default=".", help="Repo working dir (default: cwd).")
    ap.add_argument("--lines", type=parse_lines_arg,
                    help="Optional line range as 'start,end' — scopes the scan to commits that "
                         "affected those lines (follows the range through history).")
    ap.add_argument("--limit", type=int, default=800, help="Max touching-commits to scan (default 800).")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    remote = parse_remote(repo)
    target = args.file
    tp = Path(target)
    if tp.is_absolute():
        try:
            target = str(tp.resolve().relative_to(repo))
        except ValueError:
            pass

    commits = collect_commits(repo, target, args.lines, args.limit)

    # Identify reverts.
    reverts = []
    for c in commits:
        is_revert = c["subject"].strip().lower().startswith("revert") \
                    or "this reverts commit" in c["body"].lower()
        if not is_revert:
            continue
        m = REVERTS_SHA_RE.search(c["body"])
        reverted_sha = m.group(1)[:9] if m else None
        reverted_subject = None
        reverted_date = None
        if reverted_sha:
            reverted_subject = git(repo, "log", "-1", "--format=%s", reverted_sha).strip() or None
            reverted_date = git(repo, "log", "-1", "--format=%cI", reverted_sha).strip() or None
        # Date of the revert commit itself
        revert_date = git(repo, "log", "-1", "--format=%cI", c["sha"]).strip() or None
        reverts.append({
            "sha": c["sha"][:9],
            "full_sha": c["sha"],
            "date": revert_date,
            "subject": c["subject"],
            "reverted_sha": reverted_sha,
            "reverted_subject": reverted_subject,
            "reverted_date": reverted_date,
        })

    # Re-application heuristic — word-overlap with the original subject in a later commit.
    sha_pos = {c["sha"]: idx for idx, c in enumerate(commits)}
    for r in reverts:
        r["readded"] = None
        if not r["reverted_sha"] or not r.get("reverted_subject"):
            continue
        pos = sha_pos.get(r["full_sha"])
        if pos is None:
            continue
        # commits are newest-first; candidates that came AFTER the revert have lower idx
        for k in range(pos):
            cand = commits[k]
            subj = cand["subject"]
            if subj.lower().startswith("revert"):
                continue
            w_orig = set(re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", r["reverted_subject"].lower()))
            w_new = set(re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", subj.lower()))
            if len(w_orig & w_new) >= 3 and (w_orig - {"revert", "fix"}):
                readded_date = git(repo, "log", "-1", "--format=%cI", cand["sha"]).strip() or None
                r["readded"] = {"sha": cand["sha"][:9], "subject": subj, "full_sha": cand["sha"], "date": readded_date}
                break

    if args.json:
        # Reshape to the structured {revert, original, readded} form the renderer expects —
        # all fields (sha, sha_url, date, subject) live INSIDE each ref object.
        structured = []
        for r in reverts:
            revert_obj = {
                "sha": r["sha"],
                "sha_url": commit_url(remote, r["full_sha"]),
                "date": r.get("date"),
                "subject": r.get("subject"),
            }
            original_obj = None
            if r["reverted_sha"]:
                full_orig = git(repo, "rev-parse", r["reverted_sha"]).strip() or r["reverted_sha"]
                original_obj = {
                    "sha": r["reverted_sha"],
                    "sha_url": commit_url(remote, full_orig),
                    "date": r.get("reverted_date"),
                    "subject": r.get("reverted_subject"),
                }
            readded_obj = None
            if r.get("readded"):
                readded_obj = {
                    "sha": r["readded"]["sha"],
                    "sha_url": commit_url(remote, r["readded"]["full_sha"]),
                    "date": r["readded"].get("date"),
                    "subject": r["readded"].get("subject"),
                }
            structured.append({
                "revert":   revert_obj,
                "original": original_obj,
                "readded":  readded_obj,
            })
        out = {
            "file": target,
            "lines": list(args.lines) if args.lines else None,
            "scanned_commits": len(commits),
            "best_effort": True,
            "reverts": structured,
        }
        print(json.dumps(out, indent=2))
        return

    scope = f"lines {args.lines[0]}-{args.lines[1]} of " if args.lines else ""
    print(f"Scanned {len(commits)} commits touching {scope}{target}.")
    print("(Best-effort: re-application heuristic uses word-overlap; verify by hand for important findings.)")
    if not reverts:
        print("No reverts found in this scan.")
        return
    print(f"Found {len(reverts)} revert commit(s):")
    for r in reverts:
        print(f"  {r['sha']}  {r['subject']}")
        if r["reverted_sha"]:
            print(f"            reverts {r['reverted_sha']}  ({r['reverted_subject'] or 'unknown'})")
        if r.get("readded"):
            print(f"            re-applied in {r['readded']['sha']}  ({r['readded']['subject']})")
        else:
            print(f"            (no obvious re-application found — soft signal; check manually)")


if __name__ == "__main__":
    main()
