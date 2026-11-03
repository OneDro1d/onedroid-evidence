"""The register Acumen consumes: one JSONL row per claim, `argus-claims/register@1` (R-17, 02-sa-data-model §2.1).

    python3 -I register.py <run_dir> --run-id <id> --domain <domain> [--low-rule ...] [--out register.jsonl]

`source`/`locator`/`sha256` name the claim's first location (in source order); every other place it appears is in
`also_at`. `refs` are the pass behind the verdict: the disprove sides and refs for a contradiction, the prove refs
otherwise. `verdict` is evidenced, contradicted, no_evidence_published or evidence_private; `confidence: low` appears
only on a low-confidence contradiction, and `private` (holder, sha256, shown) only on evidence_private. Withdrawn claims
are left out. Within @1 fields may only be added, never renamed or removed. Stdlib only.
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verdict as V  # noqa: E402

SCHEMA = "argus-claims/register@1"
# id, text, source, sha256, verdict, refs, also_at and confidence are the fields Loom froze on 2026-10-30 for Acumen;
# schema, run_id, domain, locator and ruled are ours, added around them. evidence_private and private follow D18 of
# 2026-11-01, after the freeze; both only add to @1, and the PR says so.
REQUIRED = ("schema", "run_id", "domain", "id", "text", "source", "locator", "sha256", "verdict", "ruled", "refs",
            "also_at")
OPTIONAL = ("confidence", "private")
VERDICT_WORDS = {"EVIDENCED": "evidenced", "CONTRADICTED": "contradicted",
                 "NO EVIDENCE PUBLISHED": "no_evidence_published", V.PRIVATE: "evidence_private"}
PRIVATE_FIELDS = ("holder", "sha256", "shown")  # seen_by stays in the run record, as on the page
HEX64 = re.compile(r"^[0-9a-f]{64}$")
CLAIM_ID = re.compile(r"^C-[0-9]{3,}$")
DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def source_table(run_dir):
    """The claims.md source table as [(url, local file, sha256)], read the way the page reads it: the first cell is the
    URL (or a row number, then the URL) and the fifth is a 64-character hash. One URL with two hashes is refused."""
    rows, seen = [], {}
    path = pathlib.Path(run_dir) / "claims.md"
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0].isdigit() and len(cells) >= 2 and cells[1].startswith("http"):
            cells = cells[1:]
        if cells and cells[0].startswith("http") and len(cells) >= 5 and len(cells[4]) == 64:
            url, sha = cells[0], cells[4]
            if seen.setdefault(url, sha) != sha:
                raise ValueError(f"claims.md: {url} is listed with two hashes")
            rows.append((url, cells[1], sha))
    return rows


def snapshot_hashes(run_dir):
    """{local file name: sha256} from sources.sha256 (`sha256sum` lines); empty when the run has none (the 27 Oct
    third-party runs kept their hashes only in the claims.md source table)."""
    out = {}
    path = pathlib.Path(run_dir) / "sources.sha256"
    if not path.exists():
        return out
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            parts = line.split(None, 1)
            if len(parts) != 2:
                raise ValueError(f"sources.sha256:{n}: not a hash and a path")
            name = parts[1].strip().lstrip("*")
            out[name.rsplit("/sources/", 1)[1] if "/sources/" in name else name.removeprefix("sources/")] = parts[0]
    return out


def _confirmed(run_dir, hashes, url, name, sha):
    """The claims.md table's hash for a URL, once the run's own record agrees: the saved bytes of the table's file when
    the run kept them, else its sources.sha256 line. Anything else raises."""
    path = pathlib.PurePosixPath(name)
    if path.parts[:1] == ("sources",) and ".." not in path.parts:
        saved = pathlib.Path(run_dir) / name
        seen = hashlib.sha256(saved.read_bytes()).hexdigest() if saved.is_file() else hashes.get(name.removeprefix("sources/"))
        if seen == sha:
            return sha
    raise ValueError(f"{url}: the claims.md hash for {name} is not confirmed by the saved bytes or sources.sha256")


def _file_of(locator):
    return locator.split(" ", 1)[0].removeprefix("sources/")


def _refs(pass_name, refs):
    out = []
    for r in refs:
        if isinstance(r, dict) and "ref" not in r:
            continue
        if isinstance(r, dict):
            item = {"pass": pass_name, "ref": r["ref"]}
            if r.get("quote") is not None:
                item["quote"] = r["quote"]
        else:
            item = {"pass": pass_name, "ref": r}
        out.append(item)
    return out


def build_register(run_dir, run_id, domain, low_rule="confidence-field"):
    d = pathlib.Path(run_dir)
    claims = V.load_jsonl(d / "claims.jsonl")
    prove, disprove = V.load_jsonl(d / "prove.jsonl"), V.load_jsonl(d / "disprove.jsonl")
    judge, private = V.load_json(d / "judge.json"), V.load_json(d / "private-evidence.json")
    hashes = snapshot_hashes(d)
    by_url = {url: (name, sha) for url, name, sha in source_table(d)}
    confirmed = {}

    def sha_of(s):  # a locator naming a saved file: sources.sha256 only; one naming a place: the table's hash, confirmed
        if s["locator"].startswith("sources/"):
            return hashes.get(_file_of(s["locator"]))
        if s["url"] not in by_url:
            return None
        if s["url"] not in confirmed:
            confirmed[s["url"]] = _confirmed(d, hashes, s["url"], *by_url[s["url"]])
        return confirmed[s["url"]]

    rows = []
    for v in V.verdicts(list(claims), prove, disprove, judge, low_rule, private):
        if v["withdrawn"]:
            continue
        c = claims[v["id"]]
        first, rest = c["sources"][0], c["sources"][1:]
        if v["verdict"] == "CONTRADICTED":
            refs = _refs("disprove", V.contradiction_refs(disprove[v["id"]]))
        else:
            refs = _refs("prove", prove[v["id"]].get("refs") or [])
        row = {"schema": SCHEMA, "run_id": run_id, "domain": domain, "id": v["id"], "text": c["claim"],
               "source": first["url"], "locator": first["locator"],
               "sha256": sha_of(first),
               "verdict": VERDICT_WORDS[v["verdict"]], "ruled": v["ruled"], "refs": refs,
               "also_at": [{"source": s["url"], "locator": s["locator"], "sha256": sha_of(s)} for s in rest]}
        if v["low_confidence"]:
            row["confidence"] = "low"
        if v["verdict"] == V.PRIVATE:
            row["private"] = {k: private[v["id"]][k] for k in PRIVATE_FIELDS}
        rows.append(row)
    return rows


def _fail(row, msg):
    raise ValueError(f"{row.get('id', '?')}: {msg}")


def validate_row(row):
    """Raise ValueError unless `row` is a valid register@1 row (the same rules as schemas/register-1.schema.json)."""
    missing, extra = set(REQUIRED) - set(row), set(row) - set(REQUIRED) - set(OPTIONAL)
    if missing or extra:
        _fail(row, f"fields missing {sorted(missing)}, unexpected {sorted(extra)}")
    if row["schema"] != SCHEMA:
        _fail(row, "schema")
    if not isinstance(row["id"], str) or not CLAIM_ID.match(row["id"]):
        _fail(row, "id")
    for key in ("run_id", "domain", "text", "locator"):
        if not isinstance(row[key], str) or not row[key]:
            _fail(row, key)
    if not isinstance(row["source"], str) or not row["source"].startswith("http"):
        _fail(row, "source")
    if not isinstance(row["sha256"], str) or not HEX64.match(row["sha256"]):
        _fail(row, "sha256")
    if row["verdict"] not in VERDICT_WORDS.values():
        _fail(row, "verdict")
    if "confidence" in row and row["confidence"] != "low":
        _fail(row, "confidence")
    if ("private" in row) != (row["verdict"] == "evidence_private"):
        _fail(row, "private")
    if "private" in row:
        record = row["private"]
        if not isinstance(record, dict) or set(record) != set(PRIVATE_FIELDS) or not HEX64.match(str(record["sha256"])) \
                or not isinstance(record["holder"], str) or not record["holder"] or not DATE.match(str(record["shown"])):
            _fail(row, "private")
    if not isinstance(row["ruled"], bool):
        _fail(row, "ruled")
    if not isinstance(row["refs"], list):
        _fail(row, "refs")
    for ref in row["refs"]:
        if not isinstance(ref, dict) or ref.get("pass") not in ("prove", "disprove") or not isinstance(ref.get("ref"), str) \
                or set(ref) - {"pass", "ref", "quote"} or not isinstance(ref.get("quote", ""), str):
            _fail(row, "refs")
    if not isinstance(row["also_at"], list):
        _fail(row, "also_at")
    for loc in row["also_at"]:
        if not isinstance(loc, dict) or set(loc) != {"source", "locator", "sha256"} or not HEX64.match(str(loc["sha256"])) \
                or not isinstance(loc["source"], str) or not isinstance(loc["locator"], str):
            _fail(row, "also_at")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--domain", required=True)
    ap.add_argument("--low-rule", default="confidence-field", choices=V.LOW_RULES)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    rows = build_register(a.run_dir, a.run_id, a.domain, a.low_rule)
    for r in rows:
        validate_row(r)
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    if a.out:
        pathlib.Path(a.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
