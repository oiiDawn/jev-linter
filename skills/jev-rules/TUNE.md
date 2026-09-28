# Tune

Thresholds calibrate themselves: the agent disputes false alarms, and after 3 disputes on a rule `jev_lint.py` rewrites that rule's `warn`/`error` in `.claude/jev-calibration.json`. Tune handles what calibration cannot: rule wording and missed violations.

Data:

- `.claude/jev-log.jsonl`: one line per judgment (`id`, `path`, first 300 chars of `after`, per-rule `p` and version `v`, `flagged` tier), plus dispute lines (`dispute` = judgment id, `rule`, `reason`).
- `.claude/jev-calibration.json`: per-rule overrides; `needs_rewording: true` means true and false alarms score in the same range.

## Rule marked for rewording

1. Collect that rule's disputed flags (with reasons and snippets) and its undisputed flags, for the current version `v` only.
2. Find what the false alarms share that the true alarms lack, usually a case the wording leaves ambiguous (an allowed exception, a file type, a pattern the rule never meant).
3. Propose new wording that states the approved behaviour for that case. Show the user the old and new wording next to the evidence.
4. On approval, edit the rule in `.claude/jev-rules.toml` and delete its entry from `.claude/jev-calibration.json`. The new text gets a new version, so the old history stops counting.

## Missed violation

The user points at an edit jev should have flagged.

1. Find the judgment in the log (by path and snippet) and read that rule's `p`.
2. No judgment for that rule: its globs missed the file. Widen the globs.
3. `p` of 0.3 or more: set the rule's `warn` (or `error`, if it should block) in the TOML just below that `p`.
4. `p` below 0.3: the wording does not describe this case. Reword it, as in the section above.

## Wrong flag reported by the user

Record it as a dispute, the same way the agent does:

```
uv run --quiet --project "<plugin root>" python "<plugin root>/jev_lint.py" dispute "<repo>" <judgment-id> <rule-id> "<reason>"
```
