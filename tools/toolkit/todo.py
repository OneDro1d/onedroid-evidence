"""The "what to do" list of a run (02-sa-data-flow §7), one item per claim that needs one.

    python3 -I todo.py <run_dir> [--low-rule confidence-field|note-text] [--out todo.json]

Withdrawn, evidenced and evidence-private claims need nothing. Stdlib only. Nothing here says true or false.
"""
import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verdict as V  # noqa: E402

ACTIONS = {"owner_number": "publish the raw data behind this figure, or reword it",
           "publish_artefact": "point to the code, config or endpoint, or reword",
           "product_gap": "not visible on public surfaces: ship it publicly or reword",
           "copy": "reword as a commitment, or add a dated record"}
CATEGORIES = tuple(ACTIONS)
FIGURES = ("number", "comparison")
ARTEFACT_KINDS = ("capability", "process", "licence")


def _ref(item):
    return item.get("ref", "") if isinstance(item, dict) else item


def _contradiction(disprove_row):
    refs = [_ref(r) for r in V.contradiction_refs(disprove_row)]
    if len(refs) >= 2:
        action = f"make {refs[0]} and {refs[1]} agree"
    else:
        action = f"make the claim and {refs[0]} agree" if refs else "make the two sides agree"
    return "copy", action, refs


def _no_evidence(claim, prove_row, disprove_row):
    kind, checkability = claim["kind"], claim["checkability"]
    if kind in FIGURES:
        category = "owner_number"
    elif kind in ARTEFACT_KINDS and checkability == "A":
        category = "publish_artefact"
    elif kind == "capability" and checkability == "B":
        category = "product_gap"
    elif kind in ARTEFACT_KINDS and checkability == "B" and disprove_row.get("contradiction") != "unverifiable":
        category = "product_gap"
    else:
        category = "copy"
    return category, ACTIONS[category], [_ref(r) for r in prove_row.get("refs") or []]


def todo_row(row, claim, prove_row, disprove_row):
    """The item for one verdict row, or None when there's nothing to do."""
    if row["withdrawn"]:
        return None
    if row["verdict"] == "CONTRADICTED":
        category, action, refs = _contradiction(disprove_row)
    elif row["verdict"] == "NO EVIDENCE PUBLISHED":
        category, action, refs = _no_evidence(claim, prove_row, disprove_row)
    else:
        return None
    return {"id": row["id"], "category": category, "action": action, "refs": refs}


def todo(run_dir, low_rule="confidence-field"):
    d = pathlib.Path(run_dir)
    claims, prove, disprove = (V.load_jsonl(d / f) for f in ("claims.jsonl", "prove.jsonl", "disprove.jsonl"))
    items = (todo_row(r, claims[r["id"]], prove[r["id"]], disprove[r["id"]]) for r in V.load_run(d, low_rule))
    return [i for i in items if i]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir")
    ap.add_argument("--low-rule", default="confidence-field", choices=V.LOW_RULES)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    text = json.dumps(todo(a.run_dir, a.low_rule), indent=1, ensure_ascii=False) + "\n"
    if a.out:
        pathlib.Path(a.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
