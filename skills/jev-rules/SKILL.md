---
name: jev-rules
description: Create or tune the rules jev-lint judges edits against (.claude/jev-rules.toml). Use when setting up jev in a repo, turning CLAUDE.md / AGENTS.md / other rule files into lint rules, or when jev flags wrong things, misses violations, or marks a rule for rewording.
---

# jev-rules

A jev rule is one plain-language sentence that a model scores against a single edit (path, before, after) in isolation. It fits jev when it is **fuzzy** (no regex or ESLint rule can express it) and **judgeable from the edit alone** (no need to see other files, history, or runtime).

**Tune branch**: if `.claude/jev-calibration.json` has an entry with `"needs_rewording": true`, or the user reports a wrong flag or a missed violation, follow [TUNE.md](TUNE.md) instead of the steps below.

## Create

### 1. Sources

Sweep the repo for rule-like files: `CLAUDE.md`, `AGENTS.md` (root and nested per package), `.cursorrules`, `.cursor/rules/*`, `.github/copilot-instructions.md`, `.windsurfrules`, `CONTRIBUTING.md`, ADRs, and any other doc that states conventions. List what you found and let the user pick which to mine.

Done when the user has confirmed the source list (it may be empty).

### 2. Explore the code

Look for conventions nobody wrote down. Three kinds only:

- **Blessed module**: a shared thing that exists to be reused and is easy to bypass (a `components/ui` kit vs. raw `<button>`, an API client wrapper vs. `fetch`).
- **Owning package**: one package owns a concept (shared enums, contracts, schemas) and code elsewhere must import it, not redefine it.
- **Boundary**: a package or layer must never touch another (a worker never queries the business DB).

Formatting and naming belong to formatters and linters, so leave them out. In a large or multi-package repo, dispatch an Explore subagent to sweep and return candidates with evidence paths. Every candidate carries its evidence: the paths that show the convention.

Done when every top-level app/package has been visited.

### 3. Interview (only when steps 1–2 yield fewer than three candidates)

Ask the user:

1. What do you keep correcting agents on?
2. Which modules must always be reused?
3. Which boundaries must never be crossed?

Each answer becomes a candidate.

### 4. Triage

Put every candidate in exactly one bucket:

- **Jev**: fuzzy and judgeable from the edit alone.
- **Deterministic**: a regex, ESLint/Ruff rule, type check, or PreToolUse deny can enforce it.
- **Not lintable**: needs repo-wide context, history, or is about process ("run tests before committing").

Only the Jev bucket goes into the file. The other two are reported to the user at the end.

### 5. Draft

Write each rule so a judge seeing one diff can score it sharply:

- **One check per rule.** Two concerns become two rules.
- **Name the approved alternative**: "must import from `@acme/enums`", with the forbidden form stated after it.
- **Keep the source language**: a rule mined from a Chinese doc stays Chinese.
- **Tight globs**: the narrowest paths where the rule can actually be broken.

Above each rule, a provenance comment: `# from: AGENTS.md` or `# inferred: frontend/src/components/ui/ (Button, Input, Card)`. Leave `warn`/`error` at their defaults, except inferred rules get `error = 0.95` so a guessed rule mostly warns. Thresholds calibrate themselves later from the agent's disputes.

**Budget**: about 15 rules, and at most about 5 whose globs match any single file (all matching rules share one 5 s call that fails open). Over budget: rank by damage done when violated, and ask the user to cut or narrow globs.

Format (`id` and `rule` required; `globs`, `warn`, `error` optional; a top-level `model = "..."` overrides the Jev model):

```toml
# from: AGENTS.md
[[rule]]
id = "api-client-reuse"
rule = "Frontend code must call the backend through the client in @/lib/api, not fetch() or axios directly."
globs = ["frontend/src/**/*.ts", "frontend/src/**/*.tsx"]
```

### 6. Review

Show the draft. Rules from sources are in by default: ask only about the ambiguous ones (unclear scope, vague wording). Each **inferred** rule needs an explicit yes from the user; drop any without one.

Done when every inferred rule has a yes or is dropped.

### 7. Write

- If `.claude/jev-rules.toml` exists, merge by `id`: show the diff, add new rules, and keep existing `warn`/`error` values.
- Add `.claude/jev-log.jsonl` and `.claude/jev-calibration.json` to `.gitignore`.
- Check it parses: `python -c "import tomllib; tomllib.load(open('.claude/jev-rules.toml','rb'))"`.
- Report the **Deterministic** and **Not lintable** buckets so the user can place them elsewhere.
