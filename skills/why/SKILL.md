---
name: why
description: >-
  Code archaeology — recover the full history and *intent* behind a specific piece of
  code: what it does, the commit that first introduced it, the most recent significant
  change, the PR(s) those commits merged in, and the discussion around them in PR reviews,
  linked tickets (GitHub Issues, Linear, Jira, etc.), and team chat. Use this whenever the user asks WHY a piece of code exists, the HISTORY or
  reasoning behind a decision, "who wrote this and why", "what's the context here", or
  "what was this change for". ALSO invoke it proactively, before editing code, whenever you
  are about to make a non-trivial change to code that is unfamiliar, legacy, fragile, or
  whose intent is unclear — understanding the original reasoning prevents reintroducing bugs
  that an earlier change deliberately fixed. Also use it when reviewing someone else's change
  under those same conditions. Triggers on: git blame, code archaeology, "why is this here",
  "why was this done this way", tracing a regression to its origin, and understanding legacy
  code before changing it. Do NOT use it for runtime debugging ("why is my test failing")
  or for code with no version history.
---

# why — code archaeology

Code tells you *what* it does. It rarely tells you *why* it does it that way. The "why"
lives in history: the commit that introduced it, the PR where it was debated, the Slack
thread where someone said "we have to special-case this or the webhook retries forever."
Recovering that context is the difference between a safe change and silently undoing a
hard-won fix.

This skill runs a disciplined investigation: **code → blame → introducing & most-recent-
significant commits → PRs → PR discussion → Slack → a written report.** Follow it whenever
the goal is to understand intent, not just behavior.

## When to run this

- The user asks **why** code exists, its **history**, the **reasoning** behind a decision,
  who wrote it, or what a change was for.
- You are about to **modify code you don't fully understand** — legacy, fragile, oddly
  specific, or wrapped in a comment like "do not remove" / "HACK" / "workaround". Investigate
  *before* you edit. A five-minute history check beats reintroducing a regression.
- You are **reviewing** someone else's change and need the context they had.

If the code has no version history (untracked, brand-new, or not in a git repo), say so and
stop — there is nothing to excavate.

## The investigation

Work through these steps in order. Narrate what you find as you go; the goal is a chain of
evidence, not just an answer.

### 1. Scope the target

Pin down exactly what you're investigating: the file, and the specific function / method /
block / line range. Read it carefully first — you can't tell a significant change from
cosmetic noise later if you don't understand the code now. Note the line range; most of the
power below comes from line-scoped history.

### 2. Blame, then walk backwards

```bash
git blame -L <start>,<end> -- <file>          # who last touched these lines
git log    -L <start>,<end>:<file>            # full line-range history, newest first
```

`git log -L` is the workhorse — it shows every commit that changed those exact lines, with
diffs, so you can read the evolution directly. From it, identify two anchor commits:

- **The introducing commit** — where these lines (or the function) first appeared. Walk to
  the bottom of the `-L` history, or recurse with blame: `git blame <sha>^ -- <file>` keeps
  stepping back before each change.
- **The most recent *significant* change** — the latest commit that changed *behavior*, not
  just formatting. Skip pure renames, reindents, and import shuffles.

When the line range has moved or the file was renamed, add `--follow` and use the pickaxe to
track the actual code across moves:

```bash
git log --follow -p -- <file>
git log -S '<exact code string>' -- <file>    # commits that added/removed that string
git log -G '<regex>' -- <file>                 # commits whose diff matches the regex
```

For squash-merge repos, gnarly rebases, and monorepo path moves, see
`references/playbook.md`.

**Check for reverts** while you have the file's history in hand. A change that was added,
reverted, and then quietly re-added is a classic source of subtle bugs the next editor will
miss. Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/why/scripts/find_reverts.py" \
  --file <repo-relative-or-absolute file> --repo <repo dir> \
  [--lines <start>,<end>]                        # scope to a method/block when relevant
```

**Use `--lines` when you scoped the target to a method or block in step 1.** File-wide reverts
in a large file are usually noise: the disable! method in a 2000-line `user.rb` shouldn't
inherit revert findings about unrelated growth-experiment code. The flag follows the line
range through history (`git log -L`), so only reverts that actually affected your code
surface.

The script is **best-effort signal, not a definitive answer.** It catches explicit revert
commits (subject starts with `Revert`, or body carries the standard `This reverts commit
<sha>` trailer) and tries to spot whether the reverted change was later re-applied via
word-overlap with the original subject. Re-applications under a different title are common
and *will* be missed — the output will say "no obvious re-application found" even when one
exists. Treat hits as a signal to look more carefully, not as a fact.

JSON output includes `sha_url`, `reverted_sha_url`, and `readded_sha_url` pre-built from the
repo's remote — drop the entries straight into the sidecar's `reverts` field. The renderer
puts a short yellow banner and structured revert rows inside the **Significant changes**
panel.

For *implicit* reverts (content removed in one commit and silently added back in another,
with no `Revert` message), use the pickaxe: `git log -S '<unique snippet>' --oneline --
<file>` — if the same string is added, removed, and re-added across separate commits, that's
the pattern.

### 3. Map each anchor commit to its PR

```bash
gh api repos/{owner}/{repo}/commits/{sha}/pulls \
  --jq '.[] | {number, title, url, merged_at}'
```

If that returns nothing (e.g. the SHA is a squashed commit), fall back to searching:

```bash
gh pr list --search "<sha>" --state all --json number,title,url
gh search prs "<sha or title keywords>" --repo {owner}/{repo}
```

Get `{owner}/{repo}` from `git remote get-url origin`.

### 4. Read the discussion on each PR

The PR body and its comments are where intent is recorded.

```bash
gh pr view <number> --comments
gh pr view <number> --json title,body,reviews,comments,closingIssuesReferences,url
```

Capture: the stated purpose, objections raised and how they were resolved, follow-up TODOs,
linked issues, and anything that explains a non-obvious choice. Quote the load-bearing lines.

### 5. Follow the linked tickets

PRs and commit messages routinely cite an issue or ticket — the original intent (problem
statement, planned approach, project/initiative context) lives there. The richest signal is
often **divergence between the plan and what shipped**. Pull whatever the team uses; the
skill is system-agnostic, only the fetch tooling differs:

- **GitHub Issues.** `gh pr view <n> --json closingIssuesReferences` returns linked issues
  directly. For a specific issue: `gh issue view <number> --comments` (and `--json
  title,body,comments,labels,milestone` for everything). URL pattern:
  `https://{host}/{owner}/{repo}/issues/<n>`. GH issue IDs share the `#NNN` namespace with
  PRs — rely on `closingIssuesReferences` rather than guessing.
- **Linear.** IDs match `[A-Z][A-Z0-9]+-\d+` (e.g. `AB-4469`) or appear as `linear.app/...`
  URLs. Fetch with `mcp__claude_ai_Linear__get_issue`. Returns title, status, project,
  milestone/initiative, description, and canonical `url`. Use `list_comments` for the
  discussion if it looks load-bearing.
- **Jira.** Same `[A-Z][A-Z0-9]+-\d+` ID regex as Linear; URL pattern
  `https://<workspace>.atlassian.net/browse/<ID>`. No standard Claude MCP — if an Atlassian
  MCP isn't connected, link the URL and proceed with whatever's in the PR body.
- **Asana / Notion / other.** Search PR bodies and commit messages for URLs to the team's
  tracker; if an MCP for that host is connected (Asana, Notion, etc. — check the available
  tool list), fetch the page; otherwise link the URL and note what's behind it.

For each ticket found, capture title, status, the intended approach, the project/initiative,
and any planned-vs-shipped divergence. The `project`/`milestone` sidecar fields map to whatever
your system calls these — GitHub Milestone, Linear Project/Milestone, Jira Epic/Sprint, etc.

Best-effort: if no ticket is referenced or the relevant MCP isn't connected, say so and move on
— don't block the report. Same applies if a ticket *is* referenced but you can't read it
(private workspace, missing permissions): link the ID and note "ticket not accessible" rather
than guessing at its contents.

When reading PR comments, **separate human reviewers from bots** (CodeRabbit, kodiakhq,
dependabot): the bots' technical suggestions are still useful, but the human signal — who
objected, who approved, what concern was load-bearing — is what tells you intent. `gh pr view
<n> --json comments --jq '.comments[] | select(.author.login | endswith("[bot]") | not)'`
filters to humans.

### 6. Search Slack for the conversation around it

PRs are often debated in Slack before/after merge. Search the Slack MCP for the PR and its
topic, then read the threads:

- `slack_search_public_and_private` with the PR number, the full PR URL, the PR title, and
  distinctive keywords (function name, feature, ticket ID).
- `slack_read_thread` on promising hits to get the full exchange.

This step is best-effort. If Slack isn't connected or nothing turns up, note "no Slack
discussion found" and move on — don't block the report on it.

### 7. Map structural callers (always)

Who depends on this code *today*, independent of history. Run on every investigation:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/why/scripts/find_callers.py" \
  --symbol <method-or-class> --define-file <path-of-the-definition> --repo <repo dir>
# or, for a whole file:
python3 "${CLAUDE_PLUGIN_ROOT}/skills/why/scripts/find_callers.py" \
  --file <repo-relative-file> --repo <repo dir>
```

It runs ripgrep (with a `git grep` fallback), word-boundary-matches the symbol, drops definition
lines (`def`/`class`/`module`/…) and the definition file itself, ranks remaining files by hit
count, and prints sample lines so you can spot bogus hits at a glance. JSON output emits a
`url` per result (GitHub blob URL pinned to the first matching line) — drop the entries
straight into `used_by` without templating links.

**With `--file`, the script prefers the namespaced symbol** derived from the path (e.g.
`lib/netlify_server/client.rb` → `NetlifyServer::Client`) over the bare basename — this avoids
drowning the result in unrelated matches for generic stems like `client`, `service`, or
`handler`. If the namespaced form has any hits, only those are returned; otherwise it falls
through to CamelCase and snake_case basename matches.

### 8. Map frequent authors (always)

Who has shaped this code the most. Run on every investigation, **scoped to the line range
when you've narrowed to a method or block** — a file-wide author list for a tiny method in a
2000-line file misrepresents who actually shaped that method.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/why/scripts/find_authors.py" \
  --file <repo-relative-or-absolute file> --repo <repo dir> --top 8 --json \
  [--lines <start>,<end>]                # narrow to the target method/block
```

Counts every commit touching the file (or line range) once for its primary author and once for
each `Co-authored-by:` trailer in the message — pair-programmed work gets correct attribution.
Each entry carries a `commits` count, last-contribution timestamp, and a pre-computed gravatar
URL (MD5 of the email). Drop the JSON output into the sidecar's `frequent_authors` field; it
renders as a "Frequent authors" panel with avatars.

### 9. Map co-churn (conditional — when history is deep)

Run this **only when the target has been changed by ≥3 commits/PRs**. When code has churned
repeatedly, the files that keep changing *in the same commits* are very likely coupled and
probably must be edited together ("code-morbidity"). For single-commit code, skip it; the origin
already tells the whole story.

**Use `--lines` when the target is a method or block** — file-wide co-churn on a large file
mostly surfaces incidental neighbours (god-objects, route files, etc.); line-scoped co-churn
shows what *actually* travels with the code you care about. On `User#disable!` (lines
406–434), file-wide gives 18% account.rb / 14% authorizations test; line-scoped gives **65%
user_test.rb / 41% account.rb / 29% user_spam_check.rb** — a much sharper signal.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/why/scripts/co_churn.py" \
  --file <repo-relative-or-absolute file> --repo <repo dir> \
  [--lines <start>,<end>]               # narrow to the target method/block
```

It prints the files most often co-changed with the target (with % and sample shared commits), or
a `LOW CHURN` note if there are too few changes (then skip the co-churn section of the report).
For the strongest couplings, open one shared commit/PR to learn *why* they travel together, and
report that reason — not just the association. See `references/co-churn.md` for interpretation
(distinguishing real coupling from incidental neighbours like routes/locale files).

### 10. Synthesize and render the report

Write **two** files, then render. The markdown carries the prose; the JSON sidecar carries the
structured facts the renderer turns into chips, a **timeline**, a **commit histogram**, **change
cards**, **risk cards**, and the **dependency panels** — so the reader scans visuals first and
reads prose only where they need detail.

1. The markdown report (use the template below).
2. The structured sidecar (schema below). Omit fields you don't have rather than fabricating;
   the renderer skips empty sections gracefully.

Any paths work; below uses `/tmp/` for brevity but feel free to colocate the inputs next to the
output (e.g. an eval's workspace dir):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/why/scripts/render_report.py" \
  --markdown /tmp/why-report.md \
  --data /tmp/why-report.data.json \
  --title "why: <symbol>" \
  --slug "<repo>-<symbol>" \
  --output /optional/explicit/output/path.html
# Without --output, the HTML is written to ~/.claude/archaeology-reports/<slug>-<ts>.html
# and that path is printed to stdout.
open "$(…printed path…)"
```

The HTML has a sticky **ToC** built from your `##`/`###` headings, an **at-a-glance card** that
leads with the **most recent change** (with the origin shown smaller below — the origin is the
least-valuable signal and shouldn't dominate), the timeline + histogram, the prose underneath
with all links clickable (commits, PRs, Linear tickets, files, Slack), and a one-click "Copy
markdown" button.
It works offline. If `CLAUDE_PLUGIN_ROOT` is unset (running the skill outside the plugin), use
the script's path under this skill directory.

#### Sidecar schema (`report.data.json`)

```json
{
  "subject": "<symbol or short label>",
  "file": "app/models/foo.rb",
  "file_url": "https://github.com/.../blob/<sha>/app/models/foo.rb#L<start>-L<end>",
  "origin": {
    "sha": "abc1234", "sha_url": "https://.../commit/<full sha>",
    "pr": 1234, "pr_url": "https://.../pull/1234",
    "ticket": "ABC-123", "ticket_url": "https://linear.app/.../issue/ABC-123",
    "project": "<linear project>", "project_url": "<linear project URL>",
    "milestone": "<linear milestone or initiative>", "milestone_url": "<linear milestone URL>",
    "author": "<github login>",
    "avatar_url": "<optional. Gravatar URL — MD5(author email) per the standard gravatar pattern; find_authors.py emits these pre-computed. If omitted, the renderer resolves an avatar automatically: first from any other entry that names the same person, then by deriving github.com/<author>.png when `author` is a GitHub handle. Only a non-handle author with no match falls back to a plain colored circle (no broken images).>",
    "title": "<PR title or first line of commit message — the GitHub-style commit subject>",
    "date": "YYYY-MM-DD"
  },
  "recent": {"same_as_origin": true},
  // (When the recent change differs from origin, populate `recent` with the same shape as
  //  `origin` instead — sha/sha_url/pr/pr_url/ticket/title/author/avatar_url/date all apply.
  //  These `//` lines are documentation, not valid JSON — strip them from real sidecars.)
  "commits_total": 1,
  "events": [
    {"date":"YYYY-MM-DD","label":"short label","url":"<required — events without a URL are dropped on render>","kind":"origin|change|discussion|context"}
  ],
  "commits_by_month": {"YYYY-MM": 3, "YYYY-MM": 1},
  "coupling": [
    {"file":"path/to/other.rb","pct":42,"url":"<github blob url>"}
  ],
  "used_by": [
    {"file":"path/to/caller.rb","url":"<github blob url with #L>","hits":1}
  ],
  "risks": [
    {"title":"Short risk title (one phrase)","body":"Markdown explaining the risk, with inline links to the PR/commit/file/Slack source. Each risk should name a specific contract, gotcha, or lockstep relationship — not generic advice."}
  ],
  "frequent_authors": [
    {"name":"Mathias Biilmann","email":"info@mathias-biilmann.net","commits":44,
     "last":"2017-08-27T17:15:26-07:00",
     "avatar_url":"https://www.gravatar.com/avatar/<md5-of-email>?s=72&d=identicon"}
  ],
  "significant_changes": [
    {
      "sha":"abc1234","sha_url":"...","pr":1234,"pr_url":"...",
      "ticket":"ABC-123","ticket_url":"...",
      "title":"PR title or commit subject",
      "kind":"change | addition | removal",
      "author":"<github login>","avatar_url":"<optional — auto-resolved from the login when omitted; see the origin.avatar_url note>",
      "date":"YYYY-MM-DD",
      "snippet":"def attach_error\n  …\nend",
      "snippet_lang":"ruby",
      "snippet_url":"https://github.com/.../blob/<sha>/path/to/file.rb#L<start>-L<end>",
      "why":"One paragraph explaining what this change actually did and why — the reader's payoff."
    }
  ],
  "discussions": [
    {
      "date":"YYYY-MM-DD",
      "kind":"pr-review | slack | chat | linear | jira | ticket | documentation | rfc | notion",
      "url":"<link to the source: PR review URL, Slack permalink, ticket URL, etc.>",
      "author":"<name or handle of the person whose words this is, when known>",
      "avatar_url":"<optional — auto-resolved from the author handle when omitted; see the origin.avatar_url note>",
      "title":"<short heading: 'aitchiss review on PR #19626', '#pod-sre design discussion', 'SUP-147 ticket intent', etc.>",
      "quote":"<verbatim quote from the source — markdown allowed (use backticks for code, bold for emphasis)>",
      "body":"<optional additional context/markdown — typically the follow-up or the resolution>"
    }
  ],
  "reverts": [
    {
      "revert":   {"sha":"abc1234","sha_url":"...","pr":6229,"pr_url":"...","title":"Revert 'X'", "date":"2017-12-13"},
      "original": {"sha":"def5678","sha_url":"...","pr":6205,"pr_url":"...","title":"Original change", "date":"2017-12-10"},
      "readded":  {"sha":"ghi9012","sha_url":"...","pr":18443,"pr_url":"...","title":"What was re-applied", "date":"2019-05-22"},
      "why": "Markdown paragraph(s): WHAT was reverted (link the PR), WHY it was reverted (quote from the revert PR if available), and WHAT was re-applied (link the PR and name the specific change). Don't say 'closely related change' — name it."
    }
  ]
  // Each ref carries a `date` so the renderer can show duration between events ("3 days
  // later", "8 months later"). `find_reverts.py --json` emits this shape directly.
}
```

Notes:
- `events` drives the **timeline**. The renderer shows it **vertically, newest at the top**,
  and **drops any event without a `url`** — a timeline entry without a destination is just
  noise. Rule: if you can't link it, don't include it; if it's worth including, find the link
  (PR, commit, ticket, incident URL, Slack permalink, etc.). Include every materially-
  significant moment — do not cap or pad to a fixed count. A single-commit file might still
  have 3–5 events (ticket opened, predecessor PRs that motivated it, the origin commit, the
  rollout-announce Slack thread); a file with rich history may have 8–12 or more. Let the
  actual history set the count. The `kind` field drives colour (a legend is rendered). Use
  these values:
    - `origin` (blue) — the introducing commit.
    - `change` (red) — a commit or PR that changed behaviour.
    - `discussion` (green) — **chat-style** discussion: a Slack thread, Discord message,
      live conversation — anything ephemeral that nonetheless shaped the code.
    - `context` (gray) — **durable, written context**: a ticket opened/closed, an incident
      report, an RFC, a design doc, a project announcement. The dividing line is "chat vs
      documentation"; if it's a permanent artefact in a tracker/doc-tool, it's `context`.
- `commits_by_month` drives the **histogram**. Use the bundled helper — it emits the exact
  `{"YYYY-MM": N}` shape the schema wants and supports line-scoping for method-level
  investigations (a whole-file histogram on a 2000-line file is rarely the right framing):
  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/skills/why/scripts/commits_by_month.py" \
    --file <path> [--lines start,end]
  ```
  The renderer only draws the histogram when there are ≥3 distinct months — single-commit
  targets and very-narrow line ranges skip it.
- `coupling` is the same data you reported under "Related & co-changed files" — top 5–6, with %.
- `used_by` renders as a **collapsed "Used by" panel** — the deterministic dependency map
  from `find_callers.py`. The summary line shows just the file count ("N files"); the reader
  expands it to see the list. Each entry: the dependent file (link it to the file on GitHub,
  pinned to the line where the reference lives) and a `hits` count. Use `find_callers.py`'s
  sample-line output to *spot-check* matches before including them, but don't store the
  sample line in the sidecar — the renderer doesn't show it (and prose snippets here just add
  vertical noise).
- `risks` renders as a **"Risks & gotchas" panel** with one card per risk (same visual frame as
  significant-change cards: alert icon + bolded title, subtle HR, then a markdown body with
  inline links to the source). Don't write them as bullets in the prose — the cards live in
  the at-a-glance area. Each risk should name a specific contract, lockstep relationship, or
  known gotcha grounded in the history above, not generic advice.
- The renderer **decorates person mentions** in the prose automatically: it builds a lookup
  from `frequent_authors` (and the authors carried by `origin`/`recent`/`significant_changes`),
  then wraps any matching name/handle in the body markdown with a gravatar + linked-name chip.
  No action needed in the markdown — just populate `frequent_authors` and the cards' author
  fields, and the chips appear inline wherever you mention those people.
- `frequent_authors` renders as a **"Frequent authors" panel** with gravatars. Driven by
  `find_authors.py`, which counts every commit touching the file once for the primary author
  plus once for each `Co-authored-by:` trailer, and supplies the gravatar URL. Use ~6–10
  entries; that's enough to surface the right people to ask without becoming a noise list.
- `significant_changes` + `discussions` + `events` together drive the **"Significant
  changes" panel** — a single chronological feed (newest first) with a vertical line down
  the horizontal center:
    - The behavior-shaping commits you've curated (entries in `significant_changes`) expand
      into full-width **cards** — commit-head + optional diff snippet + why — with a 3px
      colored left strip whose color reflects `kind`: `change` (default, red), `addition`
      (green, for new functionality), or `removal` (red, for deletions).
    - The discussion items you've curated (entries in `discussions`) render as full-width
      cards with the same frame but a blockquote body for the verbatim source quote. The
      strip is **green** for chat-style sources (`pr-review`, `slack`, `chat`) and **gray**
      for written/durable sources (`linear`, `jira`, `ticket`, `documentation`).
    - The surrounding moments (entries in `events` whose URL doesn't already appear in a
      card) render as **75%-width mini-cards** centered on the line: label on the left,
      date (relative + absolute) on the right. The strip color follows `kind` the same way.
  The line is hidden by the cards (which sit on top of it) and only visible in the gaps
  between entries — visually connecting the chronology. The renderer dedupes events against
  card URLs automatically; if an event references the same PR or commit a card already
  shows, the card wins.
- `reverts` renders as a **structured sub-list at the bottom of the Significant changes panel** — placed
  next to its own short yellow banner ("N reverts found in this file's history"). The banner
  is informational only — don't editorialise about "before re-applying anything"; just
  elevate the signal. Each revert row reads chronologically (**original → revert → re-applied**)
  with **duration phrasing between successive refs** ("reverted 3 days later", "re-applied
  18 months later") computed from the `date` fields. The `why` paragraph names the exact PRs
  and the actual changes — never "closely related change" without saying what.
- **"Link it or omit it" rule for project/milestone**: only include `project` / `milestone` if
  you also have a real `project_url` / `milestone_url`. Bare text without a link is noise; the
  renderer will skip those fields when no URL is provided.
- Use proper URLs everywhere (per the Linking rules); the chips, timeline, coupling bars, change
  cards, and revert alerts all render as links.

Then give the user a 2–3 sentence spoken summary and the path to the HTML — don't make them
read the whole file to get the headline.

## Linking rules

**Every reference must be a clickable link — no bare identifiers.** Whenever you mention a PR,
commit, ticket, or file (anywhere in the report, not just a Links section), link it. Derive
`{host}/{owner}/{repo}` from `git remote get-url origin`.

| Reference | Link format |
|-----------|-------------|
| PR | `[PR #123](https://{host}/{owner}/{repo}/pull/123)` |
| Commit | `[abc1234](https://{host}/{owner}/{repo}/commit/<full-sha>)` (display 7 chars, link full SHA) |
| File | `[path/to/file.rb](https://{host}/{owner}/{repo}/blob/<sha-or-default-branch>/path/to/file.rb)` — pin to the relevant commit SHA when permanence matters; add `#L<start>-L<end>` for a line range |
| GitHub Issue | `[#123](https://{host}/{owner}/{repo}/issues/123)` — get the number from `gh pr view --json closingIssuesReferences` |
| Linear ticket | `[AB-4469](<url from get_issue>)` — use the canonical `url` the Linear MCP returns |
| Jira ticket | `[ABC-123](https://<workspace>.atlassian.net/browse/ABC-123)` |
| Linear project | `[<project name>](<canonical url from Linear MCP `get_project`>)` |
| Slack thread | `[<short label>](<message permalink>)` — copy the permalink from `slack_search_*` results |

If a ticket ID appears but the relevant fetch tool isn't reachable, still link the canonical URL
when you can construct it (you know the workspace/host); otherwise leave the bare ID and note
the system was unavailable.

## Report template

Use this structure. Apply the linking rules above to every identifier. Omit a section only if you
genuinely found nothing for it, and say so.

```markdown
# why: <symbol> — <file path>

## TL;DR
<2–4 sentences: what this code does and the single most important reason it exists / is shaped
this way. This is the headline; everything else is evidence.>

## Responsibilities
<The SOLID-SRP framing: what is this code *responsible for* — the reasons it could change —
not a method-by-method description of what it currently does. If the responsibility is
single, write ONE short sentence. If there are multiple, use a sub-list of 2–5 bullets, each
naming one cross-cutting concern. If you find yourself enumerating methods or restating the
obvious behavior, stop and rewrite at a higher level; if you can't find a coherent
responsibility beyond "it's the file," omit this section entirely — silence beats noise.>

## Origin
<Why it was introduced — the problem the original PR/ticket set out to solve and (when
relevant) any divergence between the plan and what shipped. Don't repeat the metadata (SHA,
PR #, author, date, ticket project/milestone) — those are already in the commit-head and
chips at the top of the report. This section is purely the narrative "why".>

<!-- Discussion now lives in the sidecar's `discussions` array and renders as cards on the
     timeline at each item's date. Don't write a Discussion highlights section in prose. -->

## Related & co-changed files (code-morbidity)
<Include ONLY when co_churn.py found ≥3 touching commits. This is the *deeper* breakdown of
the at-a-glance "Co-changes with this" panel — two tables (real couplings, then incidental
neighbours), both sorted by co-change % descending, with one-sentence "why they travel
together" per row. Omit the section entirely on low-churn targets. See `references/co-churn.md`.>

<!-- significant_changes render as cards from the sidecar; do not duplicate as prose bullets.
     risks render as cards from the sidecar; do not duplicate as prose bullets.
     The Origin/Recent metadata renders in the commit-head; do not repeat it in prose. -->

## Links
- Introducing commit / PR / ticket
- Most recent significant commit / PR
- Related issues, co-changed files, chat threads
```

## Notes on judgment

- **Significant vs. cosmetic.** A behavior change, a new branch, a changed default, a bug fix
  — significant. Reformatting, renaming a variable, moving a file — cosmetic. When unsure,
  read the diff; the pickaxe (`-S`/`-G`) helps confirm whether real logic moved.
- **Stop when you have the why, not when you've read everything.** The point is intent. Once
  the introducing PR and the latest behavioral change explain the current shape, you're done —
  you don't need to narrate every commit in between.
- **No history is a finding.** "This was added in the initial commit with no PR and no
  discussion" is a legitimate, useful answer. Report it plainly.

## Writing style

The reader scans the at-a-glance card first, then drops into the prose only where it matters,
so the prose has to reward scanning. A few rules:

- **Break lists of more than 3 items into a proper sub-list** — one item per line — instead of
  running them together as a comma-separated bullet or paragraph. This applies to co-authors,
  contributing PRs, affected files, sibling commits, related tickets, "other recent behavior
  changes" — anything enumerable. A comma-separated string of three or more refs is almost
  always wrong; break it up.
- Lead each section with the **conclusion**, then evidence. The reader wants the "why" first;
  the supporting commits/quotes back it up.
- **Quote load-bearing lines verbatim** with a link to the source (PR comment, ticket
  description, Slack message). One good quote beats three sentences of paraphrase.
- Keep sentences short. Eliminate hedging ("seems to", "might be") when you have evidence.
- **Report what is, not what should be.** Assume the reader is a competent expert who can
  draw their own conclusions. Skip prescriptive or advisory sentences ("X belongs in the
  subclass, not here", "be careful when…", "consider refactoring") — they waste tokens and
  read as condescension. Present the facts; the reader handles the rest.

See `references/playbook.md` for command recipes covering squash merges, force-pushed
branches, file renames/moves, GitHub Enterprise hosts, and repos with no GitHub remote.
