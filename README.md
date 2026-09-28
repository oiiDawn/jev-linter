# jev-lint

A fuzzy linter for Claude Code. After every `Edit`/`Write`, it asks Jev (TypeSafe System One) whether the change breaks one of your project's plain-language rules (in any language) — the kind no regex or ESLint rule can express, like "use the shared API client, not `fetch`".

- **p ≥ error** (default 0.85): the agent is blocked and told to fix it.
- **p ≥ warn** (default 0.5): the agent gets a heads-up.
- Anything fails (no rules, no key, timeout): the edit goes through.

## Install

Needs [uv](https://docs.astral.sh/uv/) and a TypeSafe API key.

```
/plugin marketplace add oiiDawn/jev-linter
/plugin install jev-lint
```

Set the key in `~/.claude/settings.json`:

```json
{ "env": { "TYPESAFE_API_KEY": "..." } }
```

## Write rules

In your repo, ask Claude: **"set up jev rules"**. The `jev-rules` skill reads your `CLAUDE.md` / `AGENTS.md` / other rule files, explores the code for unwritten conventions, and writes `.claude/jev-rules.toml`:

```toml
[[rule]]
id = "api-client-reuse"
rule = "Frontend code must call the backend through the client in @/lib/api, not fetch() or axios directly."
globs = ["frontend/src/**/*.ts", "frontend/src/**/*.tsx"]
```

Keep it small: about 15 rules, with narrow globs.

## Thresholds tune themselves

Every judgment is logged to `.claude/jev-log.jsonl`. When the agent decides a flag is a false alarm, it runs the `dispute` command printed in the message. After 3 disputes on a rule, its thresholds move just above the false alarms (never past 0.98) in `.claude/jev-calibration.json`. If true and false alarms score the same, the rule is marked for rewording — ask Claude to **"tune jev rules"**.

Add both files to `.gitignore`.

## Develop

```
uv run python test_jev_lint.py
```
