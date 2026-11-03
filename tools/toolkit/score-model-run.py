#!/usr/bin/env python3
"""Score a prove/disprove pass from a cheaper model against the reference pass (P2 model-cost measurement).

    python3 -I score-model-run.py <kind: prove|disprove> <reference.jsonl> <candidate.jsonl> [holdout.json]

Prints: line counts, missing/extra ids, the grade distribution of both, exact agreement, a confusion table, and the
ids where they differ (reference -> candidate). With a holdout.json ({"C-097": "yes", ...} for disprove, or
{"C-089": "artefact", ...} for prove) it also prints how many holdout rows the candidate got as expected.
The reference is the pass we are comparing against, not ground truth: a disagreement is a row to read, not a mark.
"""
import collections
import json
import sys


def load(path):
    rows = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            rows[d["id"]] = d
    return rows


def main():
    kind, ref_path, cand_path = sys.argv[1], sys.argv[2], sys.argv[3]
    field = {"prove": "evidence", "disprove": "contradiction"}[kind]
    ref, cand = load(ref_path), load(cand_path)
    print(f"reference rows {len(ref)}  candidate rows {len(cand)}")
    missing = sorted(set(ref) - set(cand))
    extra = sorted(set(cand) - set(ref))
    print(f"missing in candidate: {len(missing)} {missing[:20]}")
    print(f"extra in candidate:   {len(extra)} {extra[:20]}")
    print("reference distribution:", dict(collections.Counter(r[field] for r in ref.values())))
    print("candidate distribution:", dict(collections.Counter(r[field] for r in cand.values())))
    common = [i for i in ref if i in cand]
    agree = sum(1 for i in common if ref[i][field] == cand[i][field])
    print(f"exact agreement: {agree}/{len(common)} = {agree / max(1, len(common)):.1%}")
    conf = collections.Counter((ref[i][field], cand[i][field]) for i in common)
    print("confusion (reference -> candidate: count):")
    for (a, b), n in sorted(conf.items()):
        print(f"  {a:>12} -> {b:<12} {n}")
    diffs = [i for i in common if ref[i][field] != cand[i][field]]
    print("differences:")
    for i in diffs:
        print(f"  {i}: {ref[i][field]} -> {cand[i][field]} | {cand[i].get('note', '')[:160]}")
    if len(sys.argv) > 4:
        hold = json.load(open(sys.argv[4]))
        ok = [i for i, g in hold.items() if i in cand and cand[i][field] == g]
        bad = [(i, g, cand[i][field] if i in cand else None) for i, g in hold.items() if i not in cand or cand[i][field] != g]
        print(f"holdout: {len(ok)}/{len(hold)} as expected; misses: {bad}")


if __name__ == "__main__":
    main()
