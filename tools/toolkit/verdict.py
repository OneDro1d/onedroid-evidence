"""The one verdict rule (00-overview §4.1, R-05.1). Every other tool calls this; nothing else decides a verdict.

    python3 -I verdict.py <run_dir> [--low-rule confidence-field|note-text] [--out verdicts.jsonl]

A reviewer's ruling in <run_dir>/judge.json comes first: one of the three verdict words replaces the passes' verdict
(shown with its note); WITHDRAWN keeps the passes' verdict but drops the claim from tables and counts; any other value
is ignored, as gen-evidence-page.py always did. Then: disprove "yes" -> CONTRADICTED; else prove "artefact" ->
EVIDENCED; else EVIDENCE PRIVATE if <run_dir>/private-evidence.json has a record for the claim (D18: never set by a
pass, never over a contradiction or an artefact); else NO EVIDENCE PUBLISHED. A missing pass row is an error, never a
default. Stdlib only. Nothing here says true or false.
"""
import argparse
import collections
import json
import pathlib
import re
import sys

VERDICTS = ("EVIDENCED", "CONTRADICTED", "NO EVIDENCE PUBLISHED")
PRIVATE = "EVIDENCE PRIVATE"
WITHDRAWN = "WITHDRAWN"
PROVE_GRADES = ("artefact", "restated", "none")
DISPROVE_GRADES = ("yes", "no", "unverifiable")
LOW_RULES = ("confidence-field", "note-text")

# The note-text rule of the imported runs, exactly as gen-evidence-page.py has it: the word "low" (word boundary, so
# not "below" or "allow") together with "confiden".
LOW_WORD = re.compile(r"\blow\b", re.I)
CONFIDENCE_WORD = re.compile(r"confiden", re.I)


class MissingPassRow(ValueError):
    """A claim has no row in a pass. Raised, never defaulted (R-05.4)."""


def verdict_row(cid, prove_row, disprove_row, ruling=None, low_rule="confidence-field", private=None):
    if low_rule not in LOW_RULES:
        raise ValueError(f"unknown low-confidence rule {low_rule!r}")
    evidence = prove_row.get("evidence")
    contradiction = disprove_row.get("contradiction")
    if evidence not in PROVE_GRADES:
        raise ValueError(f"{cid}: prove evidence {evidence!r} is not one of {PROVE_GRADES}")
    if contradiction not in DISPROVE_GRADES:
        raise ValueError(f"{cid}: disprove contradiction {contradiction!r} is not one of {DISPROVE_GRADES}")

    if contradiction == "yes":
        verdict = "CONTRADICTED"
    elif evidence == "artefact":
        verdict = "EVIDENCED"
    else:
        verdict = "NO EVIDENCE PUBLISHED" if private is None else PRIVATE

    ruled_verdict = (ruling or {}).get("verdict")
    ruled = ruled_verdict in VERDICTS
    if ruled:
        verdict = ruled_verdict
    withdrawn = ruled_verdict == WITHDRAWN

    if verdict != "CONTRADICTED":
        low = False
    elif low_rule == "confidence-field":
        low = disprove_row.get("confidence") == "low"
    else:
        note = str(disprove_row.get("note", ""))
        low = bool(LOW_WORD.search(note)) and bool(CONFIDENCE_WORD.search(note))

    return {"id": cid, "verdict": verdict, "low_confidence": low, "withdrawn": withdrawn, "ruled": ruled,
            "rule": low_rule}


def verdicts(claim_ids, prove, disprove, judge=None, low_rule="confidence-field", private=None):
    """Rows in claim order. Raises MissingPassRow naming every id missing from either pass."""
    missing = [f"prove:{c}" for c in claim_ids if c not in prove] + [f"disprove:{c}" for c in claim_ids if c not in disprove]
    if missing:
        raise MissingPassRow("missing pass rows: " + ", ".join(missing))
    judge, private = judge or {}, private or {}
    return [verdict_row(c, prove[c], disprove[c], judge.get(c), low_rule, private.get(c)) for c in claim_ids]


def contradiction_refs(row):
    """A disprove row's two sides, then its remaining refs (02-sa-data-model §2.1)."""
    sides = row.get("sides") or []
    return sides + [r for r in row.get("refs") or [] if r not in sides]


def counts(rows):
    """The register's counts: withdrawn rows are left out of every count and the total."""
    shown = [r for r in rows if not r["withdrawn"]]
    c = collections.Counter(r["verdict"] for r in shown)
    out = {v: c.get(v, 0) for v in VERDICTS}
    if c.get(PRIVATE):
        out[PRIVATE] = c[PRIVATE]
    out["low"] = sum(1 for r in shown if r["low_confidence"])
    out["total"] = len(shown)
    out["withdrawn"] = len(rows) - len(shown)
    return out


def load_jsonl(path):
    p, rows = pathlib.Path(path), {}
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            row = json.loads(line)
            if not isinstance(row, dict) or "id" not in row:
                raise ValueError(f"{p.name}:{n}: a row needs an id")
            rows[row["id"]] = row
    return rows


def load_json(path):
    """A run's optional JSON file (judge.json, private-evidence.json), {} when it isn't there."""
    p = pathlib.Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def load_run(run_dir, low_rule="confidence-field"):
    d = pathlib.Path(run_dir)
    claims = load_jsonl(d / "claims.jsonl")
    return verdicts(list(claims), load_jsonl(d / "prove.jsonl"), load_jsonl(d / "disprove.jsonl"), load_json(d / "judge.json"),
                    low_rule, load_json(d / "private-evidence.json"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir")
    ap.add_argument("--low-rule", default="confidence-field", choices=LOW_RULES)
    ap.add_argument("--out", help="write verdicts.jsonl here")
    a = ap.parse_args(argv)
    rows = load_run(a.run_dir, a.low_rule)
    if a.out:
        pathlib.Path(a.out).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(json.dumps(counts(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
