#!/usr/bin/env python3
"""Gates on a claims-audit run directory, for any publisher. Reads the run, never changes it. Stdlib only.

    python3 -I gate.py draw <run_dir> [--n 21] [--seed <text>]
    python3 -I gate.py check <run_dir> --holdout <holdout.jsonl> [--previous <previous_run_dir>] [--seed <text>] [--no-draw]

private-evidence.json, when a run has one, is checked too: {"C-001": {"holder": "...", "sha256": "<64 hex>", "shown": "YYYY-MM-DD",
"seen_by": "...", "note": "..."}}. Only an artefact the holder showed us, with its hash matched by hand, goes in it. A record on a claim the passes did not
grade no evidence fails: private evidence never overrides a contradiction or stands beside a published artefact.

draw: prints the holdout ids, drawn from checks.jsonl with the seed (default: the run directory's name, which is the run id), 21
of them as in the sixth run. It refuses until both passes are merged, so no worker can have known the ids. It prints ids only.
check: prints one PASS or FAIL line per gate, then the sha256 of each run file. Exit 0 only if every gate passes. A run with
no holdout file fails, and so does one that leaves out a drawn id: agreement is a gate, not an option. --no-draw skips the drawn-id
check, for records made before this rule (1 Nov 2026).

holdout.jsonl: one object per claim, written from the sources BEFORE opening the pass rows for those ids:
{"id": "C-001", "prove": ["artefact"], "disprove": ["no", "yes"]}. Each list is the grades the orchestrator accepts; a missing
key is not checked. Hand-picked ids may be added. A disagreement fails the gate: re-check that claim by hand (RUN.md step 3).
Nothing here says true or false.
"""
import argparse
import collections
import hashlib
import json
import pathlib
import random
import re
import sys

PASSES = {"prove": ("evidence", {"artefact", "restated", "none"}), "disprove": ("contradiction", {"yes", "no", "unverifiable"})}
NO_REFS_NEEDED = {"none", "unverifiable"}
DRAW_N = 21
STATUSES = {"kept", "reworded", "new"}


def jsonl(path):
    return [json.loads(line) for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def gate_claims(run):
    ids = [c.get("id") for c in jsonl(run / "claims.jsonl")]
    dup = [i for i, n in collections.Counter(ids).items() if n > 1]
    return (bool(ids) and not dup and None not in ids), f"{len(ids)} ids, duplicates {dup}"


def gate_run_json(run):
    data = json.loads((run / "run.json").read_text(encoding="utf-8"))
    missing = [k for k in ("publisher", "domain", "hosts", "fetched_at") if not data.get(k)]
    return not missing, f"missing {missing}"


def gate_sources(run):
    listed, bad = set(), []
    for line in (run / "sources.sha256").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        path = run / name.strip().lstrip("*")
        listed.add(path.name)
        if not path.is_file() or sha(path) != digest:
            bad.append(path.name)
    saved = {p.name for p in (run / "sources").iterdir()}
    unlisted = sorted(saved - listed)
    return bool(listed) and not bad and not unlisted, f"{len(listed)} listed, mismatched {bad}, unlisted {unlisted}"


def gate_same_ids(run, name):
    want = [c["id"] for c in jsonl(run / "claims.jsonl")]
    got = [r.get("id") for r in jsonl(run / name)]
    return want == got, f"{len(got)} rows, missing {sorted(set(want) - set(got))[:10]}, extra {sorted(set(got) - set(want), key=str)[:10]}"


def gate_pass_values(run, which):
    field, allowed = PASSES[which]
    rows = jsonl(run / f"{which}.jsonl")
    bad = [r.get("id") for r in rows if r.get(field) not in allowed]
    norefs = [r.get("id") for r in rows if r.get(field) in allowed - NO_REFS_NEEDED and not r.get("refs")]
    nonote = [r.get("id") for r in rows if not r.get("note")]
    counts = dict(sorted(collections.Counter(str(r.get(field)) for r in rows).items()))
    return not (bad or norefs or nonote), f"{counts}, bad values {bad[:10]}, graded without refs {norefs[:10]}, empty notes {nonote[:10]}"


def drawn_ids(run, n, seed):
    ids = [r["id"] for r in jsonl(run / "checks.jsonl")]
    return sorted(random.Random(seed).sample(ids, min(n, len(ids))))


def gate_holdout(run, path, seed):
    rows = jsonl(path)
    left_out = sorted(set(drawn_ids(run, DRAW_N, seed)) - {r["id"] for r in rows}) if seed is not None else []
    grades = {w: {r["id"]: r.get(PASSES[w][0]) for r in jsonl(run / f"{w}.jsonl")} for w in PASSES}
    wrong = []
    for row in rows:
        for which in PASSES:
            if which in row and grades[which].get(row["id"]) not in row[which]:
                wrong.append(f"{row['id']} {which} {grades[which].get(row['id'])} not in {row[which]}")
    drew = "drawn ids not checked" if seed is None else f"drawn ids left out {left_out[:10]}"
    return bool(rows) and not wrong and not left_out, f"{len(rows)} claims, disagreements {wrong[:10]}, {drew}"


def gate_previous(run, prev):
    now = jsonl(run / "claims.jsonl")
    old = {c["id"] for c in jsonl(prev / "claims.jsonl")}
    bad = [c["id"] for c in now if c.get("status") not in STATUSES]
    new_reused = [c["id"] for c in now if c.get("status") == "new" and c["id"] in old]
    carried_unknown = [c["id"] for c in now if c.get("status") in ("kept", "reworded") and c["id"] not in old]
    absent = sorted(old - {c["id"] for c in now})
    status = dict(sorted(collections.Counter(str(c.get("status")) for c in now).items()))
    return not (bad or new_reused or carried_unknown), (f"{status}, bad status {bad[:10]}, new ids already used {new_reused[:10]}, "
                                                       f"carried ids unknown {carried_unknown[:10]}, absent {absent}")


def gate_private(run):
    records = json.loads((run / "private-evidence.json").read_text(encoding="utf-8"))
    claims = {c["id"] for c in jsonl(run / "claims.jsonl")}
    prove = {r["id"]: r for r in jsonl(run / "prove.jsonl")}
    disprove = {r["id"]: r for r in jsonl(run / "disprove.jsonl")}
    unknown = [i for i in records if i not in claims]
    malformed = [i for i, r in records.items() if not r.get("holder") or not r.get("seen_by") or not re.fullmatch(r"[0-9a-f]{64}", str(r.get("sha256")))
                 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r.get("shown")))]
    graded = [i for i in records if prove.get(i, {}).get("evidence") == "artefact" or disprove.get(i, {}).get("contradiction") == "yes"]
    return not (unknown or malformed or graded), f"{len(records)} records, unknown ids {unknown[:10]}, malformed {malformed[:10]}, not graded no evidence {graded[:10]}"


def check(run, holdout, previous, seed=None):
    gates = [("run.json", lambda: gate_run_json(run)), ("claims ids", lambda: gate_claims(run)), ("sources hashes", lambda: gate_sources(run)),
             ("checks ids", lambda: gate_same_ids(run, "checks.jsonl"))]
    for which in PASSES:
        gates.append((f"{which} ids", lambda w=which: gate_same_ids(run, f"{w}.jsonl")))
        gates.append((f"{which} grades", lambda w=which: gate_pass_values(run, w)))
    gates.append(("holdout agreement", lambda: gate_holdout(run, holdout, seed) if holdout else (False, "no holdout file given")))
    if previous:
        gates.append(("carried ids", lambda: gate_previous(run, previous)))
    if (run / "private-evidence.json").exists():
        gates.append(("private evidence", lambda: gate_private(run)))
    failed = 0
    for name, fn in gates:
        try:
            ok, detail = fn()
        except (OSError, ValueError, KeyError) as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
    for f in ("claims.jsonl", "checks.jsonl", "prove.jsonl", "disprove.jsonl", "sources.sha256"):
        if (run / f).is_file():
            print(f"{sha(run / f)}  {f}")
    print(f"{'ALL GATES PASSED' if not failed else str(failed) + ' GATE(S) FAILED'}")
    return 1 if failed else 0


def draw(run, n, seed):
    missing = [f for f in ("prove.jsonl", "disprove.jsonl") if not (run / f).is_file()]
    if missing:
        print(f"refused: draw only after both passes are merged, missing {missing}")
        return 2
    print("\n".join(drawn_ids(run, n, seed)))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("run_dir", type=pathlib.Path)
    c.add_argument("--holdout", type=pathlib.Path)
    c.add_argument("--previous", type=pathlib.Path)
    c.add_argument("--seed")
    c.add_argument("--no-draw", action="store_true")
    d = sub.add_parser("draw")
    d.add_argument("run_dir", type=pathlib.Path)
    d.add_argument("--n", type=int, default=DRAW_N)
    d.add_argument("--seed")
    a = ap.parse_args(argv)
    seed = a.seed or a.run_dir.resolve().name
    if a.cmd == "check":
        return check(a.run_dir, a.holdout, a.previous, None if a.no_draw else seed)
    return draw(a.run_dir, a.n, seed)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
