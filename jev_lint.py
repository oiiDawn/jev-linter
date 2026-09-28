"""Fuzzy linter: Claude Code PostToolUse hook that judges an edit against tiny rules with Jev.

Rules: <repo>/.claude/jev-rules.toml, re-read on every call.
Tiers: p >= error -> exit 2 (agent must fix); warn <= p < error -> advisory context; else silent.
Any failure (no rules, no TYPESAFE_API_KEY, API error/timeout) lets the edit through.

Self-calibration: every judgment is appended to <repo>/.claude/jev-log.jsonl. The agent disputes a
false alarm with `jev_lint.py dispute <repo> <judgment-id> <rule-id> "<reason>"`; once a rule has
MIN_DISPUTES disputes, its thresholds are recomputed into <repo>/.claude/jev-calibration.json
(overrides on top of the TOML, deletable). Flags that are never disputed count as true positives.
"""

import json
import os
import sys
import tomllib
import uuid
import zlib
from pathlib import Path, PurePosixPath

from typesafe_sdk import Noul, RetryPolicy, TypeSafeClient

ROOT = Path(__file__).parent
WARN, ERROR = 0.5, 0.85
LOG, CALIB = "jev-log.jsonl", "jev-calibration.json"
MIN_DISPUTES, CAP = 3, 0.98  # CAP: calibration never disables a rule


def rule_version(rule: dict) -> str:
    """Rewording a rule changes its version, which retires its old log history and calibration."""
    return f"{zlib.crc32(rule['rule'].encode()):08x}"


def load_rules(path: Path) -> tuple[str | None, list[dict]]:
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    rules = cfg.get("rule", [])
    calib_path = path.with_name(CALIB)
    if calib_path.exists():
        calib = json.loads(calib_path.read_text(encoding="utf-8"))
        for r in rules:
            c = calib.get(r["id"], {})
            if c.get("v") == rule_version(r):
                r.update({k: c[k] for k in ("warn", "error") if k in c})
    return cfg.get("model"), rules


def applies(rule: dict, rel_path: str) -> bool:
    globs = rule.get("globs")
    return not globs or any(PurePosixPath(rel_path).full_match(g) for g in globs)


def edit_state(tool: str, tool_input: dict, cwd: str) -> dict:
    path = Path(tool_input.get("file_path", ""))
    try:
        rel = path.relative_to(cwd).as_posix()
    except ValueError:
        rel = path.as_posix()
    if tool == "Write":
        before, after = "", tool_input.get("content", "")
    elif tool == "MultiEdit":
        edits = tool_input.get("edits", [])
        before = "\n...\n".join(e.get("old_string", "") for e in edits)
        after = "\n...\n".join(e.get("new_string", "") for e in edits)
    else:
        before, after = tool_input.get("old_string", ""), tool_input.get("new_string", "")
    return {"path": rel, "tool": tool, "before": before, "after": after}


def judge(client: TypeSafeClient, rules: list[dict], state: dict, model: str | None) -> dict[str, float]:
    questions = {
        r["id"]: Noul(
            instructions=f"Does the 'after' code of this edit to {state['path']} violate this rule? Rule: {r['rule']}",
            criteria={"true": "The 'after' code clearly breaks the rule.", "false": "The 'after' code follows the rule, or the rule does not apply to it."},
        )
        for r in rules
    }
    res = client.system_one(state=state, questions=questions, model=model)
    return {k: a.noul for k, a in res.nouls.items()}


def tiers(rules: list[dict], probs: dict[str, float]) -> tuple[list[str], list[str]]:
    """Rule ids at error tier and at warn tier."""
    high, medium = [], []
    for r in rules:
        p = probs.get(r["id"], 0.0)
        if p >= r.get("error", ERROR):
            high.append(r["id"])
        elif p >= r.get("warn", WARN):
            medium.append(r["id"])
    return high, medium


def recalibrate(records: list[dict], rule: dict) -> dict | None:
    """New calibration entry for `rule` from its log history, or None if too few disputes.

    One cut just above the highest disputed p. If an undisputed flag sits below the cut, no
    threshold separates true from false alarms: the rule text is ambiguous and needs rewording.
    """
    rid, v = rule["id"], rule_version(rule)
    disputed = {rec["dispute"] for rec in records if rec.get("rule") == rid and "dispute" in rec}
    fp, tp = [], []
    for rec in records:
        judged = rec.get("rules", {}).get(rid)
        if rid in rec.get("flagged", {}) and judged and judged["v"] == v:
            (fp if rec["id"] in disputed else tp).append(judged["p"])
    if len(fp) < MIN_DISPUTES:
        return None
    cut = min(CAP, round(max(fp) + 0.01, 2))
    warn, error = rule.get("warn", WARN), rule.get("error", ERROR)
    if any(p < cut for p in tp):
        return {"v": v, "warn": warn, "error": error, "needs_rewording": True}
    return {"v": v, "warn": max(warn, cut), "error": max(error, cut)}


def append_log(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def dispute(repo: str, jid: str, rid: str, reason: str) -> int:
    d = Path(repo) / ".claude"
    log = d / LOG
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line] if log.exists() else []
    rec = next((r for r in records if r.get("id") == jid), None)
    if not rec or rid not in rec.get("flagged", {}):
        print(f"jev: no flag of rule {rid} in judgment {jid}", file=sys.stderr)
        return 1
    if not reason.strip():
        print("jev: a dispute needs a reason", file=sys.stderr)
        return 1
    entry = {"dispute": jid, "rule": rid, "reason": reason}
    append_log(d / LOG, entry)
    records.append(entry)

    _, rules = load_rules(d / "jev-rules.toml")
    rule = next((r for r in rules if r["id"] == rid), None)
    new = rule and recalibrate(records, rule)
    if not new:
        print(f"jev: dispute recorded for {rid}")
        return 0
    calib_path = d / CALIB
    calib = json.loads(calib_path.read_text(encoding="utf-8")) if calib_path.exists() else {}
    calib[rid] = new
    calib_path.write_text(json.dumps(calib, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if new.get("needs_rewording"):
        print(f"jev: dispute recorded; {rid} flags true and false alarms at the same scores, marked for rewording")
    else:
        print(f"jev: dispute recorded; {rid} recalibrated to warn={new['warn']} error={new['error']}")
    return 0


def main() -> int:
    event = json.load(sys.stdin)
    cwd = event.get("cwd") or os.getcwd()
    rules_path = Path(cwd) / ".claude" / "jev-rules.toml"
    if not rules_path.exists():
        return 0
    try:
        model, rules = load_rules(rules_path)
        state = edit_state(event["tool_name"], event.get("tool_input", {}), cwd)
        rules = [r for r in rules if applies(r, state["path"])]
        if not rules:
            return 0
        with TypeSafeClient(timeout=5.0, retry=RetryPolicy(max_retries=0)) as client:  # key from TYPESAFE_API_KEY
            probs = judge(client, rules, state, model)
    except Exception as e:  # fail open: a linter must never stall the agent
        print(f"jev: skipped ({type(e).__name__}: {e})", file=sys.stderr)
        return 0

    high, medium = tiers(rules, probs)
    jid = uuid.uuid4().hex[:8]
    try:
        append_log(rules_path.with_name(LOG), {
            "id": jid, "path": state["path"], "after": state["after"][:300],
            "rules": {r["id"]: {"p": round(probs.get(r["id"], 0.0), 3), "v": rule_version(r)} for r in rules},
            "flagged": {rid: "error" for rid in high} | {rid: "warn" for rid in medium},
        })
    except OSError as e:
        print(f"jev: log not written ({e})", file=sys.stderr)

    by_id = {r["id"]: r for r in rules}
    line = lambda rid: f"[{rid}] (p={probs.get(rid, 0.0):.2f}) {by_id[rid]['rule']}"
    how = (f"\nIf a flag is a false alarm, dispute it (one command per rule, the reason is required):\n"
           f'uv run --quiet --project "{ROOT}" python "{ROOT / "jev_lint.py"}" dispute "{cwd}" {jid} <rule-id> "<reason>"')
    if high:
        print(f"jev: {state['path']} violates project rules, fix before continuing:\n" + "\n".join(map(line, high))
              + ("\nAlso double-check (lower confidence):\n" + "\n".join(map(line, medium)) if medium else "") + how, file=sys.stderr)
        return 2
    if medium:
        msg = (f"jev: possible rule violations in {state['path']} (lower confidence). "
               "Double-check the code against each rule.\n" + "\n".join(map(line, medium)) + how)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}))
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["dispute"]:
        if len(sys.argv) != 6:
            sys.exit('usage: jev_lint.py dispute <repo> <judgment-id> <rule-id> "<reason>"')
        sys.exit(dispute(*sys.argv[2:]))
    sys.exit(main())
