"""Import a notepad claims-audit run into an evidence-repo run folder (02-sa-service-map §5.4).

    python3 -I import_run.py <notepad_run_dir> <out_folder> --domain D --publisher P --run-id R
                             [--baseline-dir <notepad_run_dir> --baseline-run-id R0]

Copies the run record (never the source bytes: their hashes are in sources.sha256), then writes verdicts.jsonl (the
old note-text low-confidence rule), register.jsonl (register@1, every row validated), gates.json marked imported (those
runs were gated by hand), movement against the baseline when one is given, run.json, and manifest.sha256 over every
other file. Deterministic: the same inputs give the same bytes. Refuses a non-empty output folder. Stdlib only.
"""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import movement as M  # noqa: E402
import register as R  # noqa: E402
import verdict as V  # noqa: E402

IMPORTER = "import_run/1"
LOW_RULE = "note-text"
COPY = ("claims.jsonl", "claims.md", "prove.jsonl", "disprove.jsonl", "judge.json", "private-evidence.json",
        "sources.sha256", "prove-summary.md", "disprove-summary.md", "checks.jsonl", "checks-summary.md", "http-cache.json")


def _jsonl(rows):
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def _write(path, text):
    path.write_text(text, encoding="utf-8")


def _sources_from_table(src):
    """sources.sha256 for a run that kept its hashes only in the claims.md source table: each listed file must be a
    saved file under sources/ whose bytes hash to the table's value."""
    lines = {}
    for _url, name, sha in R.source_table(src):
        path = src / name
        if not name.startswith("sources/") or ".." in pathlib.PurePosixPath(name).parts or not path.is_file():
            raise ValueError(f"claims.md lists {name}, which is not a saved file under sources/")
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError(f"{name}: the saved bytes don't match the hash in claims.md")
        lines[name] = f"{sha}  {name}\n"
    return "".join(lines[name] for name in sorted(lines))


def import_run(src_dir, out_dir, domain, publisher, run_id, baseline_dir=None, baseline_run_id=None, fetched_at=None):
    """`fetched_at`: from the import map, for a run that kept no run.json (r1); one that contradicts the run's own is
    refused."""
    src, out = pathlib.Path(src_dir), pathlib.Path(out_dir)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} is not empty")
    original = json.loads((src / "run.json").read_text(encoding="utf-8")) if (src / "run.json").exists() else {}
    if fetched_at and original.get("fetched_at") not in (None, fetched_at):
        raise ValueError(f"fetched_at {fetched_at} contradicts the run's own {original['fetched_at']}")
    from_table = None if (src / "sources.sha256").exists() else _sources_from_table(src)
    out.mkdir(parents=True, exist_ok=True)

    for name in COPY:
        if (src / name).exists():
            shutil.copyfile(src / name, out / name)
    if from_table is not None:
        _write(out / "sources.sha256", from_table)

    _write(out / "run.json", json.dumps({
        "run_id": run_id, "publisher": publisher, "domain": domain,
        "imported": True, "imported_from": src.name, "importer": IMPORTER,
        "fetched_at": original.get("fetched_at") or fetched_at, "hosts": original.get("hosts", []),
        "repo_commit": original.get("repo_commit"), "previous_run": baseline_run_id,
        "note": original.get("note"),
    }, indent=1, ensure_ascii=False) + "\n")

    rows = V.load_run(src, LOW_RULE)
    _write(out / "verdicts.jsonl", _jsonl(rows))

    register = R.build_register(src, run_id, domain, LOW_RULE)
    for r in register:
        R.validate_row(r)
    _write(out / "register.jsonl", _jsonl(register))

    _write(out / "gates.json", json.dumps({
        "version": 1, "imported": True, "gates": [],
        "note": "Imported run: gated by hand in the notepad session (orchestrator holdout + reading), not by gates.py.",
    }, indent=1) + "\n")

    if baseline_dir:
        m = M.movement_between(baseline_dir, src, LOW_RULE)
        m["baseline_run"] = baseline_run_id
        _write(out / "movement.json", json.dumps(m, indent=1, ensure_ascii=False) + "\n")
        _write(out / "MOVEMENT.md", M.to_markdown(m))

    manifest = []
    for p in sorted(out.rglob("*")):
        rel = p.relative_to(out).as_posix()
        if p.is_file() and rel != "manifest.sha256":
            manifest.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {rel}\n")
    _write(out / "manifest.sha256", "".join(manifest))

    return {"run_id": run_id, "counts": V.counts(rows), "files": len(manifest) + 1}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--domain", required=True)
    ap.add_argument("--publisher", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--baseline-dir")
    ap.add_argument("--baseline-run-id")
    ap.add_argument("--fetched-at", help="for a run with no run.json: its fetch time from the import map")
    a = ap.parse_args(argv)
    print(json.dumps(import_run(a.src, a.out, a.domain, a.publisher, a.run_id, a.baseline_dir, a.baseline_run_id,
                                a.fetched_at)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
