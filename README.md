# why — code archaeology for Claude Code

> Recover the *intent* behind a piece of code, not just what it does.

`why` is a [Claude Code](https://claude.com/claude-code) skill that turns the question
**"why does this code exist?"** into a disciplined investigation: it walks the file's git
history, maps commits to PRs, pulls the ticket and chat discussion that shaped each PR, and
hands back a self-contained HTML report you can refer to later.

It runs **on demand** when you type `/why`, and (more importantly) **proactively** — Claude
reaches for it on its own before editing unfamiliar, legacy, or fragile code, so a change
doesn't silently undo an earlier fix.

---

## The problem

Code tells you *what* it does. It rarely tells you *why* it does it that way. The "why"
lives in history: the commit that introduced it, the PR where it was debated, the Slack
thread where someone said "we have to special-case this or the webhook retries forever." If
you change the code without knowing that, you reintroduce the bug an earlier change
deliberately fixed.

Doing this manually is tedious: `git blame`, walk back through commits, fish out PR numbers,
read review comments, hunt for the ticket, search Slack, cross-reference everything. It's
exactly the kind of work a model is good at — *if* it has a disciplined process to follow.
That's what this skill is.

---

## What it does (in 10 steps)

1. **Scope the target** — file + line range / specific symbol.
2. **`git blame` + `git log -L`** to find the introducing commit and the most recent
   *significant* (behavioral) change. Also runs `find_reverts.py --lines` to detect
   revert / re-apply chains within the line range.
3. **Map commits → PRs** via `gh api` (and search-fallback for squash-merge SHAs).
4. **Read PR review discussion** (humans filtered from bots like CodeRabbit / kodiakhq).
5. **Follow the linked tickets** — system-agnostic. Recognizes GitHub Issues, Linear,
   Jira, Asana, Notion, and "any URL referenced in the PR body."
6. **Search team chat** (Slack via MCP today; the pattern extends to any chat MCP).
7. **Map structural callers** with `find_callers.py` — namespace-aware so it doesn't
   drown in generic-name noise.
8. **Map frequent authors** with `find_authors.py` — including `Co-authored-by:` trailers,
   with pre-computed gravatar URLs. `--lines` scopes to a method when you've narrowed.
9. **Map co-churn (code-morbidity)** with `co_churn.py` — files that historically change
   in the same commits as your target. Conditional on ≥3 touching commits; `--lines`
   scopes to a method or block.
10. **Synthesize and render** — emit a markdown report + structured JSON sidecar, then
    `render_report.py` produces a single self-contained HTML file (every PR / commit /
    ticket / file / chat thread is a clickable link).

---

## What you get

A single, offline-renderable HTML file with:

- A **chronological "Significant changes" feed** down a vertical timeline. Notable commits
  expand into full cards (commit-head + diff snippet + the *why*); discussion items
  (PR reviews, Slack threads, ticket descriptions) interleave as cards in their place;
  smaller context moments render as 75%-width mini cards. Each card carries a colored 3px
  left strip — green for additions / discussion, red for changes / removals, gray for
  context.
- A **"Risks & gotchas" panel** of cards synthesizing the historical signal into
  actionable warnings: contracts that must hold, files that change in lockstep, known
  gotchas grounded in specific PRs / threads / tickets.
- Collapsed-by-default **Frequent authors**, **Used by** (structural callers), and
  **Co-changes with this** (temporal coupling) panels for the people and dependencies
  behind the code.
- A **commit-cadence histogram** of touching commits per month.
- **Person chips** in the prose: any mentioned author whose handle/email the skill knows
  gets a gravatar + linked name inline.
- GitHub-flavored markdown rendering with syntax-highlighted code (highlight.js + GitHub
  themes, light/dark adaptive), an auto-built ToC sidebar, and a one-click "Copy markdown"
  button so the report content drops cleanly into a comment or doc.

---

## When it triggers

- **Explicit:** type `/why`.
- **Auto-trigger on questions:** "why does this code exist", "what's the history of X",
  "who wrote this and why", "what's the context here".
- **Auto-trigger before risky edits:** Claude reaches for it on its own when about to
  modify code that's unfamiliar, legacy, fragile, or whose intent is unclear — the kind
  of change that silently regresses hard-won fixes if you skip the history check.
- **During code review:** when reading someone else's change and needing the context
  they had.
- **Anti-trigger:** *not* for runtime debugging ("why is my test failing"). Use a debugger
  for that. `why` is for archaeology, not introspection.

---

## How to use it

After installation, just ask Claude *why* something exists, or start editing risky code.
The model will detect the context and invoke the skill on its own. To trigger explicitly:

```
/why what's the deal with `safe_to_spam_with_paid_user?` in app/models/user.rb?
```

```
/why give me the lay of the land on app/controllers/application_controller.rb
```

```
/why I'm about to refactor lib/orb/subscription.rb — what should I know?
```

The skill will spend a minute or two walking the history, then open the rendered HTML
report in your browser and give you a 2-3 sentence spoken summary with the key takeaways.

---

## Requirements

| | |
|--- |--- |
| **`git`** | Required. The entire blame walk depends on it. |
| **[`gh`](https://cli.github.com/) CLI** | Required, authenticated (`gh auth status`). Maps commits to PRs, fetches discussion, finds linked issues. |
| **Python 3.9+** | Required. All bundled scripts; standard library only. |
| **[ripgrep](https://github.com/BurntSushi/ripgrep)** | Optional. `find_callers.py` uses it when available; falls back to `git grep` otherwise. |
| **Linear MCP** | Optional. Used for `mcp__claude_ai_Linear__get_issue` / `get_project`. Without it, Linear ticket IDs in PR bodies are still linked but not fetched. |
| **Slack MCP** | Optional. Used for `slack_search_public_and_private` / `slack_read_thread`. Without it, the Slack step skips gracefully. |
| **Any other MCP** (Atlassian/Jira, Asana, Notion, …) | Optional. The skill is tool-system-agnostic — it'll use whatever MCP is connected to fetch a linked ticket or doc URL. |

The HTML report is self-contained (marked.js + highlight.js + Primer Octicons all vendored
offline) so once generated it works without any of the above.

---

## Install

This repo is a [Claude Code plugin marketplace](https://claude.com/claude-code) containing
a single plugin. Install it from GitHub:

```
/plugin marketplace add jah2488/why
/plugin install why
```

Or from a local clone:

```
/plugin marketplace add /path/to/why
/plugin install why
```

After install, `/why` is available in every Claude Code session.

---

## Output

Reports go to `~/.claude/archaeology-reports/<repo>-<symbol>-<timestamp>.html` by default.
The path is printed to stdout and the file is auto-opened in your browser. Pass `--output`
to the renderer if you want them colocated next to a project (e.g., when running an eval).

The HTML is fully offline-capable — drop it on a USB stick, email it, paste it into a wiki:
links to GitHub / Linear / Slack work wherever the recipient can reach those services, and
the rendered content (code blocks, timeline, cards) works without any network at all.

---

## Customization

### Built-in themes

The report ships with two themes, selectable from the **theme button in the top-right** of
every report. Selection is persisted per browser via `localStorage`, so reports you open
later remember the choice.

- **Default** — adapts to OS preference (light by day, GitHub-style dark by night).
- **Terminal** — a Charm-inspired dark theme: deep near-black with a slight violet cast,
  hot-pink primary accent, cyan / lime / amber semantic colors. Always dark regardless of
  OS preference.

### Theming via CSS variables

The HTML report's appearance is themeable through CSS variables. The `:root` block at the
top of `skills/why/assets/report_template.html` defines:

- Colors — `--bg`, `--fg`, `--accent`, `--c-change`, `--c-discussion`, `--c-addition`,
  `--c-removal`, etc. (Each has a dark-mode counterpart under `@media (prefers-color-scheme: dark)`.)
- Spacing scale — `--space-xs/sm/md/lg/xl`.
- Typography scale — `--font-xs/sm/md/lg/xl`.
- Radii — `--radius-sm/md/lg/pill`.
- Component sizes — `--avatar-size`, `--dot-size`, `--oc-size`.
- History-track layout — `--history-bar-width`, `--history-mini-width`, etc.

To rebrand, override just the `:root` block; no component CSS should need to change. The
**built-in Terminal theme lives under `:root[data-theme="terminal"]`** (attribute selectors
beat plain `:root` for specificity), so:

- Overriding `:root` re-themes the Default theme.
- Overriding `:root[data-theme="terminal"]` re-themes Terminal.
- To override *both* at once, use the combined selector `:root, :root[data-theme="terminal"]`.

---

## How it's built

```
why/                                  ← git repo = single-plugin marketplace
├── .claude-plugin/
│   ├── marketplace.json              ← marketplace manifest (source: "./")
│   └── plugin.json                   ← plugin manifest
├── README.md  ·  LICENSE  ·  .gitignore
└── skills/why/
    ├── SKILL.md                      ← workflow + sidecar schema + linking rules
    ├── scripts/
    │   ├── _git_urls.py              ← shared remote/URL/line-range helpers
    │   ├── find_reverts.py           ← explicit revert detection (with --lines)
    │   ├── find_callers.py           ← who references this symbol (namespace-aware)
    │   ├── find_authors.py           ← rank authors incl. Co-authored-by trailers (with --lines)
    │   ├── co_churn.py               ← temporal coupling (with --lines)
    │   ├── commits_by_month.py       ← histogram data
    │   └── render_report.py          ← markdown + sidecar JSON → self-contained HTML
    ├── assets/
    │   ├── report_template.html      ← layout, theme tokens, render JS
    │   ├── marked.min.js             ← vendored markdown renderer (MIT)
    │   ├── highlight.min.js          ← vendored syntax highlighter (BSD-3-Clause)
    │   ├── hljs-github-light.css
    │   └── hljs-github-dark.css
    └── references/
        ├── playbook.md               ← edge-case recipes (squash merges, renames, no-remote)
        └── co-churn.md               ← interpreting the co_churn output
```

The skill itself is mostly **SKILL.md** — a single document the model follows step by step
on every invocation. The scripts handle the deterministic heavy lifting (git plumbing, URL
templating, gravatar hashing) so the model focuses on judgment: choosing the line range,
identifying significant vs cosmetic changes, separating real coupling from incidental
neighbors, writing the prose narrative.

---

## Attribution

This skill bundles three third-party libraries, each used under its own license:

- **[marked](https://github.com/markedjs/marked) v12.0.2** — MIT. Renders markdown in the HTML report.
- **[highlight.js](https://github.com/highlightjs/highlight.js) v11.9.0** — BSD-3-Clause. Syntax-highlights snippets inside cards.
- **[Primer Octicons](https://github.com/primer/octicons)** — MIT. Used for the inline SVG icons (`commit`, `pull-request`, `tag`, `person`, `calendar`, `file-code`, `comment-discussion`, `alert`, `link-external`, `chevron-right`). The individual SVG path data is inlined into `skills/why/assets/report_template.html`.

The skill also composes [Gravatar](https://en.gravatar.com/site/implement/) URLs from git
author emails per the public Gravatar URL spec; the avatar images themselves are served
by gravatar.com on demand and are not bundled.

See the full text in [`LICENSE`](./LICENSE).

---

## License

MIT — see [`LICENSE`](./LICENSE).

Contributions and issues welcome at [github.com/jah2488/why](https://github.com/jah2488/why).
