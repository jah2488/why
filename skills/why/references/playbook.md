# Playbook: tricky history recipes

Read this when the straightforward `git log -L` → `gh api .../pulls` chain in SKILL.md
doesn't resolve cleanly. Each section is a self-contained recipe.

## Contents
- [Squash-merged repos](#squash-merged-repos)
- [The line range moved or the file was renamed](#the-line-range-moved-or-the-file-was-renamed)
- [Force-pushed / rebased branches](#force-pushed--rebased-branches)
- [Commit maps to no PR](#commit-maps-to-no-pr)
- [Monorepos and path moves](#monorepos-and-path-moves)
- [GitHub Enterprise / non-github hosts](#github-enterprise--non-github-hosts)
- [No GitHub remote at all](#no-github-remote-at-all)
- [Merge commits hiding the real author](#merge-commits-hiding-the-real-author)

## Squash-merged repos

When a repo squashes PRs, `main` has one commit per PR and the original commit SHAs don't
exist there. `git blame` points at the squash commit — which is good: that commit's message
usually ends with `(#123)`.

```bash
git log -1 --format='%s%n%b' <sha>     # look for "(#123)" or "Merge pull request #123"
```

Extract the PR number from the subject line and go straight to `gh pr view <n>`. If there's
no number in the message, fall back to `gh pr list --search "<sha>"` and
`gh search prs "<title keywords>" --repo {owner}/{repo}`.

## The line range moved or the file was renamed

`git log -L a,b:file` fails or shows a truncated history when lines shifted a lot or the file
was renamed. Track the *content* instead of the *position*:

```bash
git log --follow -p -- <file>                  # follows across renames
git log -S '<unique code substring>' --oneline # pickaxe: when the string was added/removed
git log -G '<regex>' --oneline                  # diff-content regex
git log --follow --diff-filter=A -- <file>      # the commit that ADDED the file
```

`git blame -C -C -C <file>` detects lines copied or moved from other files, useful when code
was extracted into a helper.

## Force-pushed / rebased branches

The merged commit on `main` may differ from what the PR page shows (the PR retains the
pre-rebase commits). Trust `main`'s blame for *what shipped*, but read the PR's own commit
list and discussion for *intent*:

```bash
gh pr view <n> --json commits --jq '.commits[].oid'
```

If blame lands on a rebase/merge artifact, use the pickaxe to find where the actual logic
entered, then map that to its PR.

## Commit maps to no PR

`gh api repos/{owner}/{repo}/commits/{sha}/pulls` returns `[]` for direct pushes to the
default branch, or for very old history.

```bash
gh pr list --search "<sha>" --state all --json number,title,url
gh api "repos/{owner}/{repo}/commits/{sha}" --jq '.commit.message'   # may name the PR/issue
```

If there is genuinely no PR — a direct commit — that is itself the finding. Report the commit,
author, date, and message, and note "committed directly, no PR".

## Monorepos and path moves

Always scope to the path and follow moves between packages:

```bash
git log --follow -p -- packages/<pkg>/src/<file>
git log -S '<symbol>' -- '**/<file>'           # find the symbol anywhere in the tree
```

In a monorepo, also check whether the relevant PR touched other packages — the rationale may
live in a sibling change.

## GitHub Enterprise / non-github hosts

`gh` works against Enterprise if configured. Check the host and pass it explicitly:

```bash
git remote get-url origin                       # e.g. git@github.example.com:org/repo.git
gh api --hostname github.example.com repos/{owner}/{repo}/commits/{sha}/pulls
```

If `gh auth status` shows you're not logged into that host, tell the user and proceed with
git-only findings (commit, author, date, message) plus whatever the commit message references.

## No GitHub remote at all

For GitLab/Bitbucket/self-hosted/local-only repos, `gh` won't help. Still deliver value from
git alone:

```bash
git log -L <a>,<b>:<file>                        # full line history with diffs and messages
git show <sha>                                   # the full introducing change + message
```

Commit messages, `Co-authored-by`, and any `Refs:`/`Fixes:` trailers often contain the intent.
Note in the report that PR/Slack context wasn't reachable.

## Merge commits hiding the real author

`git blame` may land on a merge commit. Ignore merges to find the real change:

```bash
git log --no-merges -L <a>,<b>:<file>
git blame --first-parent -L <a>,<b> -- <file>
```
