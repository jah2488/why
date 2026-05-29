#!/usr/bin/env python3
"""Deterministic dependency map: find files that reference a symbol.

The "who uses this?" question is too expensive to ask an LLM to grep a whole repo for
on every investigation, but it's cheap with ripgrep and a couple of well-chosen filters.
This script handles the noise so the skill can drop the result straight into the report's
`used_by` panel.

Usage:
    find_callers.py --symbol <name> [--repo .] [--define-file <path>]
                    [--top 12] [--samples 2] [--json]
    find_callers.py --file <path>   [--repo .] [--top 12] [--samples 2] [--json]

For --symbol:
  Word-boundary search for <name>, then drop any line that *defines* it
  (`def`/`class`/`module`/`function`/`fn`/`interface`/`type` followed by <name>) and any line
  inside --define-file. Rank remaining files by hit count.

For --file:
  Searches in order of specificity, then merges hits:
    1. The path-derived **namespaced symbol** (e.g. lib/payment_gateway/client.rb →
       `PaymentGateway::Client` for Ruby) — most precise, lowest noise.
    2. The plain CamelCase form (`Client`) — catches imports/aliases.
    3. The snake_case basename (`client`) — catches lower-case references.
  When a namespaced form is found, prefer its hits in the ranked output (they dominate the
  signal). For very generic basenames (`client`, `service`, `handler`), the namespaced form is
  the only one that won't drown the result in unrelated matches.

Defaults exclude `vendor/`, `node_modules/`, `.git/`, and binary directories.

JSON output includes a `url` (GitHub blob URL pinned to the first matching line) per file, so
callers can feed the panel directly without templating links themselves.

Output: human-readable text (default) or JSON (`--json`). Uses ripgrep when available,
falls back to `git grep`. Python 3.9; stdlib only.
"""
import argparse
import collections
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Sibling module — scripts dir is on sys.path automatically.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_urls import parse_remote, default_branch, blob_url  # noqa: E402


EXCLUDES_RG = ["--glob", "!vendor/**", "--glob", "!node_modules/**",
               "--glob", "!.git/**", "--glob", "!**/dist/**", "--glob", "!**/build/**"]


def have_rg():
    return shutil.which("rg") is not None


def run(cmd, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd).stdout


def search_word(repo: Path, name: str):
    """Run a word-boundary search for `name` under repo. Returns lines like 'path:line:content'."""
    if have_rg():
        cmd = ["rg", "-w", "--no-heading", "--with-filename", "-n",
               "--max-columns", "300", *EXCLUDES_RG, name, "."]
        return run(cmd, cwd=repo)
    # git grep fallback — works in a git repo, respects .gitignore.
    return run(["git", "grep", "-n", "-w", name], cwd=repo)


DEF_KEYWORDS = r"(def|class|module|function|fn|interface|type|trait|struct)"


def parse_hits(raw: str, name: str, define_file: str = None, repo: Path = None):
    """Group matches by file, dropping definition lines and the define-file itself."""
    # For namespaced names (containing `::`), don't apply the def-keyword filter — definitions
    # rarely include the full namespaced form on the def line.
    namespaced = "::" in name
    leaf = name.rsplit("::", 1)[-1] if namespaced else name
    define_re = re.compile(rf"\b{DEF_KEYWORDS}\s+{re.escape(leaf)}\b")
    define_file_abs = None
    if define_file:
        p = Path(define_file)
        if not p.is_absolute() and repo:
            p = repo / p
        try:
            define_file_abs = str(p.resolve())
        except OSError:
            define_file_abs = str(p)
    hits = collections.defaultdict(list)
    for line in raw.splitlines():
        # Format: <path>:<lineno>:<content>
        try:
            path, ln, content = line.split(":", 2)
        except ValueError:
            continue
        try:
            int(ln)
        except ValueError:
            continue
        if define_file_abs:
            try:
                abs_path = str((repo / path).resolve()) if repo else str(Path(path).resolve())
                if abs_path == define_file_abs:
                    continue
            except OSError:
                pass
        if define_re.search(content):
            continue
        hits[path].append((int(ln), content.strip()))
    return hits


def snake_to_camel(s):
    """user_avatar → UserAvatar; preserves segments like v4."""
    return "".join(p[:1].upper() + p[1:] for p in s.split("_") if p)


# Common Rails-ish subdirs we strip when deriving a namespace from a path.
RAILS_APP_SUBDIRS = {"models", "controllers", "services", "workers", "jobs", "helpers",
                     "mailers", "channels", "policies", "decorators", "serializers",
                     "presenters", "queries", "commands", "operations", "concerns",
                     "validators", "uploaders"}


def derive_namespace(file_path: str):
    """Path → namespaced Ruby-style symbol, e.g. lib/payment_gateway/client.rb → PaymentGateway::Client.

    Strips leading `app/<subdir>/` (Rails autoload roots) and `lib/`, CamelCases each remaining
    path segment, drops the `.rb` extension. Returns None for paths that don't fit the pattern.
    """
    p = Path(file_path)
    parts = list(p.parts)
    if not parts:
        return None
    # Strip Rails autoload roots
    if parts[0] == "app" and len(parts) >= 3 and parts[1] in RAILS_APP_SUBDIRS:
        parts = parts[2:]
    elif parts[0] == "lib":
        parts = parts[1:]
    if not parts:
        return None
    # Drop extension on the final segment
    last = parts[-1]
    if "." in last:
        last = last[: last.rfind(".")]
    parts = parts[:-1] + [last]
    return "::".join(snake_to_camel(seg) for seg in parts if seg)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--symbol", help="Method / class / module name to find references of.")
    g.add_argument("--file", help="File whose dependents to find (derives candidate symbols from the path).")
    ap.add_argument("--repo", default=".", help="Repo working dir (default: cwd).")
    ap.add_argument("--define-file", help="Definition site path; matches in this file are excluded.")
    ap.add_argument("--top", type=int, default=12, help="Max files to report (default 12).")
    ap.add_argument("--samples", type=int, default=2, help="Sample lines per file (default 2).")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    remote = parse_remote(repo)
    branch = default_branch(repo)

    # Build candidate symbols (most specific first).
    candidates = []
    if args.symbol:
        candidates.append(args.symbol)
        define_file = args.define_file
    else:
        ns = derive_namespace(args.file)
        if ns and "::" in ns:
            candidates.append(ns)             # 1. PaymentGateway::Client (most specific)
        stem = Path(args.file).stem
        camel = snake_to_camel(stem)
        if camel and camel not in candidates:
            candidates.append(camel)          # 2. Client
        if stem and stem not in candidates:
            candidates.append(stem)           # 3. client
        define_file = args.define_file or args.file

    # Search strategy: try the most-specific candidate first. If it has any hits, that's
    # authoritative — return only those. Otherwise fall through to looser candidates. This
    # prevents a generic basename like `client` from drowning a namespaced match like
    # `PaymentGateway::Client` in unrelated noise.
    combined = collections.defaultdict(list)
    used_candidates = []
    for sym in candidates:
        raw = search_word(repo, sym)
        hits = parse_hits(raw, sym, define_file=define_file, repo=repo)
        if hits:
            for path, lines in hits.items():
                combined[path].extend(lines)
            used_candidates.append(sym)
            # If this was the namespaced form and it produced hits, stop here — anything
            # broader will only add noise.
            if "::" in sym:
                break
    candidates = used_candidates or candidates

    ranked = sorted(combined.items(), key=lambda kv: -len(kv[1]))[:args.top]

    if args.json:
        results = []
        for p, lines in ranked:
            # Dedupe by line number while preserving order
            seen = set()
            dedup = []
            for ln, content in lines:
                if ln in seen:
                    continue
                seen.add(ln)
                dedup.append((ln, content))
            first_line = dedup[0][0] if dedup else None
            results.append({
                "file": p,
                "hits": len(dedup),
                "url": blob_url(remote, branch, p, line=first_line),
                "samples": dedup[:args.samples],
            })
        out = {
            "repo": str(repo),
            "candidates": candidates,
            "results": results,
        }
        print(json.dumps(out, indent=2))
        return

    print(f"Searched for: {', '.join(candidates)}  (in {repo})")
    if not ranked:
        print("No callers found.")
        return
    print(f"Top {len(ranked)} dependents:\n")
    for path, lines in ranked:
        print(f"  {len(lines):>3}  {path}")
        for ln, content in lines[:args.samples]:
            snippet = content if len(content) <= 110 else content[:110] + "…"
            print(f"        {ln}: {snippet}")


if __name__ == "__main__":
    main()
