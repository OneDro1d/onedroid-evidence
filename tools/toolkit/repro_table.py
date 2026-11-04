"""What this code reproduces of the published runs, as hashes (Loom's request, thread 2026-11-02).

    python3 -I repro_table.py <imports/domain.json> <runs root> <exclusions.json> [--md out.md] [--json out.json]

Every value is computed, none is typed in:
- counts: verdict.py over the record's passes and judge.json, compared with the published counts in the import map;
- claims.jsonl: rebuilt by lister.assemble from the previous run's claims and this run's saved sources. The wording of
  reworded claims and the new claims are read from the record, because those are the lister model's output;
- prove.jsonl and disprove.jsonl: model output. Code reads them and cannot produce them, so their hashes here identify
  the record and prove nothing about this code.
Stdlib only.
"""
import argparse
import hashlib
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lister as LI  # noqa: E402
import locate as L  # noqa: E402
import verdict as V  # noqa: E402

PASSES_STATUS = "model output, read from the record"


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _rows(path):
    return [json.loads(l) for l in pathlib.Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def _dump(claims):
    return "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in claims).encode("utf-8")


def rebuild(prev_dir, run_dir, id_high_water, domain, rules):
    """(status, built sha256, record sha256). Rewordings and new claims come from the record; code does the rest."""
    record = (pathlib.Path(run_dir) / "claims.jsonl").read_bytes()
    real = _rows(pathlib.Path(run_dir) / "claims.jsonl")
    proposals = {"reworded": [{"prev_id": c["id"], "text": c["claim"]} for c in real if c.get("status") == "reworded"],
                 "new": [{"text": c["claim"], "kind": c["kind"], "checkability": c["checkability"]}
                         for c in real if c.get("status") == "new"]}
    sources = L.load_run_sources(run_dir, domain=domain, rules=rules)
    out = LI.assemble(_rows(pathlib.Path(prev_dir) / "claims.jsonl"), sources, proposals, id_high_water)
    built = _dump(out["claims"])
    return ("rebuilt" if built == record else "not rebuilt"), _sha(built), _sha(record)


def repro_rows(import_map, runs_root, rules):
    root = pathlib.Path(runs_root)
    domain = import_map["domain"]
    rows, previous, high = [], None, 0
    for e in import_map["runs"]:
        d = root / e["folder"].removeprefix("claims-audit-")
        counts = V.counts(V.load_run(d, "note-text"))
        claims_sha = _sha((d / "claims.jsonl").read_bytes())
        status, built = "no previous run", None
        if previous is not None:
            high = max([high] + [int(c["id"][2:]) for c in _rows(previous / "claims.jsonl")])
            status, built, _ = rebuild(previous, d, high, domain, rules)
        rows.append({"order": e["order"], "run_id": e["run_id"], "counts": counts,
                     "counts_match_published": all(counts[k] == v for k, v in e["published"].items()),
                     "claims_status": status, "claims_built_sha256": built, "claims_record_sha256": claims_sha,
                     "prove_record_sha256": _sha((d / "prove.jsonl").read_bytes()),
                     "disprove_record_sha256": _sha((d / "disprove.jsonl").read_bytes()),
                     "passes_status": PASSES_STATUS})
        previous = d
    return rows


def to_markdown(rows):
    out = ["# Reproduction table: the six published onedroid.ai runs", "",
           "Every value is computed by `toolkit/repro_table.py`. Hashes are the first 8 characters of the sha256; the",
           "full values are in the JSON next to this file.", "",
           "| # | run | claims | evidenced | contradicted (low) | no evidence | counts = published | claims.jsonl built | claims.jsonl record | claims.jsonl result | prove record | disprove record |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        c = r["counts"]
        built = r["claims_built_sha256"][:8] if r["claims_built_sha256"] else "—"
        out.append(f"| {r['order']} | {r['run_id']} | {c['total']} | {c['EVIDENCED']} | {c['CONTRADICTED']} ({c['low']}) | "
                   f"{c['NO EVIDENCE PUBLISHED']} | {'yes' if r['counts_match_published'] else 'NO'} | {built} | "
                   f"{r['claims_record_sha256'][:8]} | {r['claims_status']} | {r['prove_record_sha256'][:8]} | "
                   f"{r['disprove_record_sha256'][:8]} |")
    out += ["", "**How to read it.**",
            "- **Counts:** `verdict.py` over the record's passes and `judge.json`. The published numbers come from the",
            "  live change log; run 3's published text gives only its contradicted count.",
            "- **claims.jsonl:** rebuilt by `lister.py` from the previous run's claims and this run's saved sources. The",
            "  wording of reworded claims and the new claims are read from the record, because they are the lister",
            "  model's output. So this proves the carrying, locating and id logic, not a fresh listing.",
            "- **prove.jsonl, disprove.jsonl:** " + PASSES_STATUS + ". Code cannot produce them, and a new grading run",
            "  will not match them byte for byte. Their hashes identify the record; they prove nothing about this code.",
            "- **Run 1:** it has no previous run. **Run 2:** not rebuilt, because run 1's claims were lightly paraphrased",
            "  and run 2 re-quoted them under the same ids, still marked kept; its new ids are also not in source order.", ""]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("import_map")
    ap.add_argument("runs_root")
    ap.add_argument("rules")
    ap.add_argument("--md")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    rows = repro_rows(json.loads(pathlib.Path(a.import_map).read_text(encoding="utf-8")), a.runs_root,
                      json.loads(pathlib.Path(a.rules).read_text(encoding="utf-8")))
    if a.md:
        pathlib.Path(a.md).write_text(to_markdown(rows), encoding="utf-8")
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    print(to_markdown(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
