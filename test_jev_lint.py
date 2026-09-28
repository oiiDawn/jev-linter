"""Offline check of the deterministic parts (globs, state, tiers, calibration). Run: uv run python test_jev_lint.py"""

import json
import tempfile
from pathlib import Path

from jev_lint import CAP, applies, dispute, edit_state, load_rules, recalibrate, rule_version, tiers

r = {"id": "x", "rule": "r", "globs": ["frontend/**/*.tsx"]}
assert applies(r, "frontend/src/a/b.tsx") and applies(r, "frontend/b.tsx")
assert not applies(r, "backend/src/b.tsx") and not applies(r, "frontend/src/b.ts")
assert applies({"id": "y", "rule": "r"}, "anything.py")

s = edit_state("Edit", {"file_path": "E:/repo/backend/a.ts", "old_string": "o", "new_string": "n"}, "E:/repo")
assert s == {"path": "backend/a.ts", "tool": "Edit", "before": "o", "after": "n"}, s
assert edit_state("Write", {"file_path": "E:/repo/a.ts", "content": "c"}, "E:/repo")["after"] == "c"
assert edit_state("MultiEdit", {"file_path": "E:/repo/a.ts", "edits": [{"old_string": "1", "new_string": "2"}] * 2}, "E:/repo")["after"] == "2\n...\n2"

rules = [{"id": "a", "rule": "A"}, {"id": "b", "rule": "B"}, {"id": "c", "rule": "C", "error": 0.95}]
assert tiers(rules, {"a": 0.9, "b": 0.6, "c": 0.9}) == (["a"], ["b", "c"])
assert tiers(rules, {"a": 0.1, "b": 0.49, "c": 0.0}) == ([], [])

# --- calibration ---
rule = {"id": "a", "rule": "A"}
v = rule_version(rule)


def flag(jid, p, rid="a", ver=v):
    return {"id": jid, "rules": {rid: {"p": p, "v": ver}}, "flagged": {rid: "error"}}


def disp(jid, rid="a"):
    return {"dispute": jid, "rule": rid, "reason": "fine"}


fps = [flag("f1", 0.86), flag("f2", 0.9), flag("f3", 0.88)]
assert recalibrate(fps + [disp("f1"), disp("f2")], rule) is None  # too few disputes
c = recalibrate(fps + [disp("f1"), disp("f2"), disp("f3"), flag("t1", 0.97)], rule)
assert c == {"v": v, "warn": 0.91, "error": 0.91}, c
c = recalibrate(fps + [disp("f1"), disp("f2"), disp("f3"), flag("t1", 0.87)], rule)  # true alarm below a false one
assert c["needs_rewording"] and c["error"] == 0.85, c
assert recalibrate([flag("f1", 0.99), flag("f2", 0.99), flag("f3", 0.99), disp("f1"), disp("f2"), disp("f3")], rule)["error"] == CAP
old = [flag(j, 0.9, ver="deadbeef") for j in ("f1", "f2", "f3")]  # history of a reworded rule is ignored
assert recalibrate(old + [disp("f1"), disp("f2"), disp("f3")], rule) is None

# --- dispute end to end: calibration file is written and layered on the TOML ---
with tempfile.TemporaryDirectory() as repo:
    d = Path(repo) / ".claude"
    d.mkdir()
    (d / "jev-rules.toml").write_text('[[rule]]\nid = "a"\nrule = "A"\n', encoding="utf-8")
    (d / "jev-log.jsonl").write_text("".join(json.dumps(x) + "\n" for x in fps), encoding="utf-8")
    assert dispute(repo, "nope", "a", "fine") == 1 and dispute(repo, "f1", "a", " ") == 1
    for jid in ("f1", "f2", "f3"):
        assert dispute(repo, jid, "a", "fine") == 0
    _, loaded = load_rules(d / "jev-rules.toml")
    assert loaded[0]["error"] == 0.91 and loaded[0]["warn"] == 0.91, loaded
print("ok")
