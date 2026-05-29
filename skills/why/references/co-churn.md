# Co-churn / code-morbidity — interpretation

Read this when `scripts/co_churn.py` returns coupling and you need to turn the raw numbers into
insight. The script answers *which files change in the same commits as the target*; your job is
to decide which couplings are **real** (they must change together) versus **incidental**, and to
explain *why* the real ones are coupled.

## When it applies

Only when the target has **≥3 touching commits/PRs**. For single-commit code the script prints
`LOW CHURN` — there is no churn pattern to learn from, so omit the co-churn section entirely.

## Reading the output

Each row is `co_changes  pct  file  [sample shared commits]`:
- **pct** = share of the target's analyzed commits that also touched this file.
- High pct + a focused, related path = strong signal they're genuinely coupled.

## Separating real coupling from noise

Some files co-change with almost everything and carry little signal. Be skeptical of:
- **Routing / config** (`config/routes.rb`, `config/application.rb`) — touched by most controller work.
- **Locale / i18n, schema dumps** (`db/schema.rb`), generated files, lockfiles, `CHANGELOG`.
- **Giant god-objects** (`user.rb`, `site.rb` in many Rails apps) — coupled to everything by gravity, not by a specific contract.

Strong, meaningful couplings instead look like:
- A model + its **concern/serializer/policy/decorator**.
- A controller + its **request/serializer specs** or the **service object** it calls.
- A pair that share a **data contract** (one writes a field, the other reads it).
- Sibling files in the **same feature** that always ship together.

## Turn association into a reason

For the top 1–3 meaningful couplings, open one shared commit or PR
(`git show <sha> --stat`, `gh pr view <n>`) and read *why* both files changed. Report the reason,
not just the percentage — e.g. "every change to `parse_token` also touches
`auth_middleware.rb` because the token-validator is registered there, so the two are a unit." That
sentence is the payoff; a bare coupling table is not.

## In the report

Render the coupling as **two separate tables**, both sorted by co-change % descending:

1. **Real couplings** first — columns: *File · Co-change · Why they travel together*.
2. **Incidental neighbours** second — columns: *File · Co-change · Why it shows up*.

Don't use a single combined table with a "Verdict" column — separating the lists puts the real
findings at the top where they belong and removes a column the reader has to scan. Apply the
Linking Rules to every file. Fold "must change in lockstep" couplings into the sidecar's
`risks` array too (they render as Risks & gotchas cards) — that's what protects the next editor.
