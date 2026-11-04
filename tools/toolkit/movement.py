"""What changed between a baseline run and a new run (02-sa-data-flow §7). Replaces compare-runs.py.

    python3 -I movement.py <baseline_run_dir> <new_run_dir> [--json movement.json] [--md MOVEMENT.md]

Kept / reworded / new come from the new run's claim status (an id the baseline doesn't have is new whatever its status
says); absent = baseline ids the new run doesn't list. Verdicts come from verdict.py. The baseline is the domain's
published run, so ids retired between two published runs are never lost. Stdlib only.
"""
import argparse
import collections
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verdict as V  # noqa: E402


def movement(base_claims, base_verdicts, new_claims, new_verdicts, baseline_run=None, new_withdrawn=()):
    base_ids = [c["id"] for c in base_claims]
    base_set = set(base_ids)
    new_ids = {c["id"] for c in new_claims}
    kept, reworded, new = [], [], []
    for c in new_claims:
        if c["id"] not in base_set:
            new.append(c["id"])
        elif c.get("status") == "reworded":
            reworded.append(c["id"])
        else:
            kept.append(c["id"])
    absent = [cid for cid in base_ids if cid not in new_ids]

    # Only verdicts that were shown on both sides can move: a withdrawn row (either run) carries its id but no
    # published verdict.
    moved = [{"id": cid, "from": base_verdicts[cid], "to": new_verdicts[cid]}
             for cid in kept + reworded
             if base_verdicts.get(cid) and new_verdicts.get(cid) and base_verdicts[cid] != new_verdicts[cid]]
    moved.sort(key=lambda m: int(m["id"][2:]))
    moves = collections.Counter(f"{m['from']}->{m['to']}" for m in moved)
    from_contradicted = collections.Counter(
        (new_verdicts[cid] if cid in new_ids else "absent")
        for cid in base_ids if base_verdicts.get(cid) == "CONTRADICTED")
    return {"baseline_run": baseline_run, "total": len(new_claims) - len(set(new_withdrawn)),
            "kept": kept, "reworded": reworded, "new": new, "absent": absent,
            "moves": dict(moves), "moved": moved, "from_contradicted": dict(from_contradicted)}


def _run(run_dir, low_rule):
    d = pathlib.Path(run_dir)
    claims = list(V.load_jsonl(d / "claims.jsonl").values())
    rows = V.load_run(d, low_rule)
    shown = {r["id"]: r["verdict"] for r in rows if not r["withdrawn"]}
    withdrawn = [r["id"] for r in rows if r["withdrawn"]]
    return claims, shown, withdrawn


def movement_between(base_dir, new_dir, low_rule="note-text"):
    """Every baseline id counts for carrying, withdrawn ones too (the 28 Oct change log: "230 carry a 27 October id",
    three of them withdrawn before the 27 Oct publication); only shown verdicts count for moves."""
    base_claims, base_verdicts, _ = _run(base_dir, low_rule)
    new_claims, new_verdicts, new_withdrawn = _run(new_dir, low_rule)
    return movement(base_claims, base_verdicts, new_claims, new_verdicts, pathlib.Path(base_dir).name, new_withdrawn)


def to_markdown(m):
    out = [f"# Movement against {m['baseline_run'] or 'the baseline'}", "",
           f"{m['total']} claims: {len(m['kept'])} kept, {len(m['reworded'])} reworded, {len(m['new'])} new; "
           f"{len(m['absent'])} absent.", "", "| from -> to | count |", "|---|---|"]
    for k, n in sorted(m["moves"].items(), key=lambda kv: -kv[1]):
        a, b = k.split("->")
        out.append(f"| {a} -> {b} | {n} |")
    out += ["", "| id | from | to |", "|---|---|---|"]
    out += [f"| {x['id']} | {x['from']} | {x['to']} |" for x in m["moved"]]
    if m["absent"]:
        out += ["", "Absent: " + ", ".join(m["absent"]) + "."]
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("baseline")
    ap.add_argument("new")
    ap.add_argument("--low-rule", default="note-text", choices=V.LOW_RULES)
    ap.add_argument("--json")
    ap.add_argument("--md")
    a = ap.parse_args(argv)
    m = movement_between(a.baseline, a.new, a.low_rule)
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(m, indent=1) + "\n", encoding="utf-8")
    if a.md:
        pathlib.Path(a.md).write_text(to_markdown(m), encoding="utf-8")
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in m.items() if k != "moved"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
