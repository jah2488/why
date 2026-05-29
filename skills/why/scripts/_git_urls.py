"""Shared helpers for the why scripts: resolve a repo's GitHub-style remote into URL builders.

Every script that emits SHAs, file paths, or PR/issue numbers should also emit the matching
URLs so the model doesn't have to template them (a class of subtle bugs we'd rather not
have). Import what you need from here.

Python 3.9; stdlib only.
"""
import argparse
import re
import subprocess
from pathlib import Path


def parse_lines_arg(s):
    """argparse type for a '<start>,<end>' line range. Used by every script that takes --lines."""
    if not s:
        return None
    m = re.match(r"^(\d+)\s*,\s*(\d+)$", s.strip())
    if not m:
        raise argparse.ArgumentTypeError("expected --lines as 'start,end' (e.g. 459,472)")
    a, b = int(m.group(1)), int(m.group(2))
    if a > b:
        a, b = b, a
    return (a, b)


def parse_remote(repo):
    """Returns (host, owner, name) parsed from `git remote get-url origin`, or None."""
    try:
        url = subprocess.run(
            ["git", "-C", str(repo), "remote", "get-url", "origin"],
            capture_output=True, text=True,
        ).stdout.strip()
    except Exception:
        return None
    if not url:
        return None
    # Forms: https://host/owner/name(.git)? or git@host:owner/name(.git)?
    m = re.match(r"^(?:https?://([^/]+)/|git@([^:]+):)([^/]+)/([^/.]+?)(?:\.git)?/?$", url)
    if not m:
        return None
    return (m.group(1) or m.group(2), m.group(3), m.group(4))


def default_branch(repo):
    """Returns the default branch (e.g. 'main', 'master') via origin/HEAD; falls back to 'main'."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
        if out:
            return out.rsplit("/", 1)[-1]
    except Exception:
        pass
    return "main"


def blob_url(remote, branch, path, line=None, end_line=None):
    """`https://host/owner/name/blob/<branch>/<path>` with optional #L<line> or #L<a>-L<b>."""
    if not remote:
        return None
    host, owner, name = remote
    u = f"https://{host}/{owner}/{name}/blob/{branch}/{path}"
    if line is not None:
        u += f"#L{line}"
        if end_line is not None and end_line != line:
            u += f"-L{end_line}"
    return u


def commit_url(remote, sha):
    if not remote or not sha:
        return None
    host, owner, name = remote
    return f"https://{host}/{owner}/{name}/commit/{sha}"


def pr_url(remote, n):
    if not remote or not n:
        return None
    host, owner, name = remote
    return f"https://{host}/{owner}/{name}/pull/{n}"


def issue_url(remote, n):
    if not remote or not n:
        return None
    host, owner, name = remote
    return f"https://{host}/{owner}/{name}/issues/{n}"
