#!/usr/bin/env python3
"""Compare two claims-audit runs claim by claim (same id = same claim, re-quoted) and write a movement report.

    python3 -I compare-runs.py <previous_run_dir> <new_run_dir> <out.md> [--judge previous/judge.json]

Both dirs hold claims.jsonl, prove.jsonl, disprove.jsonl. Verdict rule is the register's (gen-evidence-page.py):
disprove yes -> CONTRADICTED (low confidence when the note has the word "low" with "confidence"); else prove artefact ->
EVIDENCED; else NO EVIDENCE PUBLISHED. A judge.json WITHDRAWN entry drops the id from the previous run's counts, as the
published register did. Stdlib only. Nothing here says true or false.
"""
import collections
import json
import pathlib
import re
import sys

LOW = re.compile(r"\blow\b", re.I)


def load(p):
    rows = {}
    for line in pathlib.Path(p).read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line)
            rows[o["id"]] = o
    return rows


def passes(d):
    d = pathlib.Path(d)
    return load(d / "claims.jsonl"), load(d / "prove.jsonl"), load(d / "disprove.jsonl")


def verdict(cid, prove, disprove):
    d = disprove.get(cid, {})
    if d.get("contradiction") == "yes":
        n = d.get("note", "")
        return "CONTRADICTED (low confidence)" if (LOW.search(n) and "confidence" in n.lower()) else "CONTRADICTED"
    if prove.get(cid, {}).get("evidence") == "artefact":
        return "EVIDENCED"
    return "NO EVIDENCE PUBLISHED"


def esc(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def main(argv):
    prev_dir, new_dir, out = argv[1], argv[2], pathlib.Path(argv[3])
    judge = {}
    if "--judge" in argv:
        judge = json.loads(pathlib.Path(argv[argv.index("--judge") + 1]).read_text(encoding="utf-8"))
    withdrawn = {k for k, v in judge.items() if v.get("verdict") == "WITHDRAWN"}
    pc, pp, pd = passes(prev_dir)
    nc, np_, nd = passes(new_dir)
    pv = {cid: verdict(cid, pp, pd) for cid in pc if cid not in withdrawn}
    nv = {cid: verdict(cid, np_, nd) for cid in nc}

    def tally(v):
        c = collections.Counter(x.split(" (")[0] for x in v.values())
        low = sum(1 for x in v.values() if x.endswith("(low confidence)"))
        return c, low

    pcnt, plow = tally(pv)
    ncnt, nlow = tally(nv)
    kept = [cid for cid in nc if cid in pv]
    new = [cid for cid in nc if cid not in pc]
    absent = [cid for cid in pv if cid not in nc]
    moved = [(cid, pv[cid], nv[cid]) for cid in kept if pv[cid].split(" (")[0] != nv[cid].split(" (")[0]]
    moves = collections.Counter((a.split(" (")[0], b.split(" (")[0]) for _, a, b in moved)
    status = collections.Counter(nc[cid].get("status", "") for cid in nc)

    L = []
    L.append(f"# Claims audit movement: {pathlib.Path(prev_dir).name} -> {pathlib.Path(new_dir).name}")
    L.append("")
    L.append("| run | claims | EVIDENCED | CONTRADICTED (low) | NO EVIDENCE PUBLISHED |")
    L.append("|---|---|---|---|---|")
    L.append(f"| previous | {len(pv)} | {pcnt.get('EVIDENCED', 0)} | {pcnt.get('CONTRADICTED', 0)} ({plow}) | {pcnt.get('NO EVIDENCE PUBLISHED', 0)} |")
    L.append(f"| new | {len(nv)} | {ncnt.get('EVIDENCED', 0)} | {ncnt.get('CONTRADICTED', 0)} ({nlow}) | {ncnt.get('NO EVIDENCE PUBLISHED', 0)} |")
    L.append("")
    L.append(f"Carried ids: {len(kept)} (lister status: {dict(status)}). New ids: {len(new)}. Absent: {len(absent)} {absent}. "
             f"Withdrawn before the previous publication and excluded from its counts: {sorted(withdrawn)}.")
    L.append("")
    L.append("## Carried claims that changed verdict")
    L.append("")
    L.append("| from -> to | count |")
    L.append("|---|---|")
    for (a, b), n in sorted(moves.items(), key=lambda x: -x[1]):
        L.append(f"| {a} -> {b} | {n} |")
    L.append("")
    L.append("| id | previous | new | claim now | disprove note now |")
    L.append("|---|---|---|---|---|")
    for cid, a, b in moved:
        L.append(f"| {cid} | {a} | {b} | {esc(nc[cid]['claim'][:160])} | {esc(nd.get(cid, {}).get('note', '')[:200])} |")
    L.append("")
    L.append("## Carried claims still CONTRADICTED")
    L.append("")
    L.append("| id | verdict | claim now | disprove note |")
    L.append("|---|---|---|---|")
    for cid in kept:
        if nv[cid].startswith("CONTRADICTED") and pv[cid].startswith("CONTRADICTED"):
            L.append(f"| {cid} | {nv[cid]} | {esc(nc[cid]['claim'][:160])} | {esc(nd[cid].get('note', '')[:240])} |")
    L.append("")
    L.append("## New claims graded CONTRADICTED")
    L.append("")
    L.append("| id | verdict | claim | disprove note | refs |")
    L.append("|---|---|---|---|---|")
    for cid in new:
        if nv[cid].startswith("CONTRADICTED"):
            L.append(f"| {cid} | {nv[cid]} | {esc(nc[cid]['claim'][:160])} | {esc(nd[cid].get('note', '')[:240])} | {esc('<br>'.join(nd[cid].get('refs', [])[:3]))} |")
    L.append("")
    L.append("## New claims by verdict")
    L.append("")
    nvc = collections.Counter(nv[cid].split(" (")[0] for cid in new)
    for k in ("EVIDENCED", "CONTRADICTED", "NO EVIDENCE PUBLISHED"):
        L.append(f"- {k}: {nvc.get(k, 0)}")
    L.append("")
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(json.dumps({"previous": {"n": len(pv), **pcnt, "low": plow}, "new": {"n": len(nv), **ncnt, "low": nlow},
                      "kept": len(kept), "new_ids": len(new), "absent": absent,
                      "moves": {f"{a}->{b}": n for (a, b), n in moves.items()}}))


if __name__ == "__main__":
    main(sys.argv)
