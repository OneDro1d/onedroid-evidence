"""Write a run's merged files (02-sa-data-flow §7): verdicts.jsonl, report.md, register.jsonl, todo.json.

    python3 -I merge_run.py <run_dir> --run-id <id> --domain <domain> [--low-rule ...] [--out <dir, default run_dir>]

Replaces merge.py. On a run with no rulings its report is merge.py's, byte for byte. The verdicts come from verdict.py,
so rulings and private evidence count, and a missing pass row is an error, never a default. Deterministic. Stdlib only.
Nothing here says true or false.
"""
import argparse
import collections
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import register as R  # noqa: E402
import todo as T  # noqa: E402
import verdict as V  # noqa: E402

WORDS = ("EVIDENCED", "CONTRADICTED", "NO EVIDENCE PUBLISHED")


def _esc(text):
    return text.replace("|", "\\|").replace("\n", " ")


def _ref_text(item):
    quote = item.get("quote") if isinstance(item, dict) else None
    return f'{T._ref(item)} "{quote}"' if quote else str(T._ref(item))


def _refs(items, n=3):
    """Structured references in full. String ones are cut as merge.py cuts them, to keep its report byte for byte."""
    items = items or []
    return "<br>".join(_esc(_ref_text(r)) for r in (items if any(isinstance(r, dict) for r in items) else items[:n]))


def _why(prove_row, disprove_row):
    sub = ["restated only" if prove_row.get("evidence") == "restated" else "nothing beyond the claim"]
    if disprove_row.get("contradiction") == "unverifiable":
        sub.append("not checkable from the publisher's surfaces")
    return ", ".join(sub)


def report(run_dir, low_rule="confidence-field"):
    d = pathlib.Path(run_dir)
    run = V.load_json(d / "run.json")
    disputed = V.load_json(d / "disputed.json")
    private = V.load_json(d / "private-evidence.json")
    judge = V.load_json(d / "judge.json")
    claims, prove, disprove = (V.load_jsonl(d / f) for f in ("claims.jsonl", "prove.jsonl", "disprove.jsonl"))
    rows = [r for r in V.load_run(d, low_rule) if not r["withdrawn"]]
    pub, date = run["publisher"], str(run["fetched_at"])[:10]
    counts = collections.Counter(r["verdict"] for r in rows)
    words = WORDS + ((V.PRIVATE,) if counts[V.PRIVATE] else ())
    by_class = collections.defaultdict(collections.Counter)
    for r in rows:
        by_class[claims[r["id"]]["checkability"]][r["verdict"]] += 1
    src_rows = [l for l in (d / "claims.md").read_text(encoding="utf-8").splitlines() if l.startswith("| https://")]

    def of(verdict):
        return [r["id"] for r in rows if r["verdict"] == verdict]

    ruled = {r["id"] for r in rows if r["ruled"]}

    def ruling(cid):
        return f"Ruled: {judge[cid].get('note', '')}"

    out = [f"# Claims audit: {pub}'s own public claims against {pub}'s own public evidence ({date})", "",
           f"**What this is.** A claims register for {pub} ({run['domain']}). A lister agent extracted every checkable claim from the sources below; a prove-it agent",
           "looked for the strongest evidence for each on the publisher's own public surfaces (the saved pages, the public repo when there is one, unauthenticated GETs); a",
           "disprove-it agent looked for contradictions on the same surfaces. Three verdicts only: **EVIDENCED** (an independent artefact on the publisher's own surfaces would be",
           "false if the claim were), **CONTRADICTED** (the publisher's own surfaces disagree with the claim), **NO EVIDENCE PUBLISHED** (the claim is stated, nothing beyond the",
           "statement backs it). No verdict says a claim is true or false: outside evidence was not used. Re-run: fetch each source, compare the sha256, re-read the references.",
           "", f"## Sources (fetched {date})", "", "| Source URL | Local file | HTTP | Bytes | sha256 |", "|---|---|---|---|---|", *src_rows, "",
           f"Also read: public repo at `{run.get('repo_commit') or 'none'}`; unauthenticated GETs to the hosts named in run.json: {', '.join(run.get('hosts', []))}.",
           "", "## Result", "", "| Verdict | Claims |", "|---|---|"]
    out += [f"| {w} | {counts.get(w, 0)} |" for w in words]
    out += [f"| total | {len(rows)} |", "",
            "By the lister's checkability class (A = checkable from the pages, B = needs outside evidence or live product access, C = value statement embedding a fact):",
            "", "| Class | " + " | ".join(words) + " |", "|---" * (len(words) + 1) + "|"]
    out += [f"| {cls} | " + " | ".join(str(by_class[cls].get(w, 0)) for w in words) + " |" for cls in sorted(by_class)]
    out += ["", "## CONTRADICTED (fix these; each quotes both sides)", "", "| id | claim | contradiction (disprove pass) | refs |", "|---|---|---|---|"]
    for cid in of("CONTRADICTED"):
        row = disprove[cid]
        note = (f"⚠️ {disputed[cid]} " if cid in disputed else "") + row.get("note", "")
        out.append(f"| {cid} | {_esc(claims[cid]['claim'])} | {_esc(ruling(cid) if cid in ruled else note)} | {_refs(V.contradiction_refs(row), 4)} |")
    out += ["", "## NO EVIDENCE PUBLISHED (publish the artefact, reword, or drop)", "", "| id | class | claim | why (prove / disprove notes) |", "|---|---|---|---|"]
    for cid in of("NO EVIDENCE PUBLISHED"):
        why = ruling(cid) if cid in ruled else f"{_why(prove[cid], disprove[cid])}. P: {prove[cid].get('note', '')} D: {disprove[cid].get('note', '')}"
        out.append(f"| {cid} | {claims[cid]['checkability']} | {_esc(claims[cid]['claim'])} | {_esc(why)} |")
    if counts[V.PRIVATE]:
        out += ["", "## EVIDENCE PRIVATE (shown to us, not published; a reader can't check it from here)", "", "| id | claim | holder | shown | sha256 |", "|---|---|---|---|---|"]
        out += [f"| {cid} | {_esc(claims[cid]['claim'])} | {_esc(private[cid]['holder'])} | {private[cid]['shown']} | {private[cid]['sha256']} |" for cid in of(V.PRIVATE)]
    out += ["", "## EVIDENCED (the artefact that backs each)", "", "| id | claim | artefact | refs |", "|---|---|---|---|"]
    for cid in of("EVIDENCED"):
        note = ruling(cid) if cid in ruled else prove[cid].get("note", "")
        out.append(f"| {cid} | {_esc(claims[cid]['claim'])} | {_esc(note)} | {_refs(prove[cid].get('refs') or [], 3)} |")
    out += ["", "## Method notes and limits", "",
            "- Three agents (lister, prove, disprove) of one owner. Raw passes: `claims.jsonl`, `prove.jsonl`, `disprove.jsonl` (hashes in the journal).",
            "- A claim repeated on several pages is one claim and counts as restated, never as evidence.",
            "- The prove pass may grade an artefact that lives outside the pages (a repo path, a live endpoint); those are listed in the EVIDENCED refs so a reader can check without the pages.",
            "- Not covered: anything outside the sources above, anything behind a sign-in.",
            "- The verdict words are deliberate: nothing here says true or false. Outside evidence would be a second audit.", ""]
    return "\n".join(out) + "\n"


def _jsonl(rows):
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def build_files(run_dir, run_id, domain, low_rule="confidence-field"):
    """({file name: bytes}, verdict rows). Nothing is written, so a failure leaves nothing behind."""
    rows = V.load_run(run_dir, low_rule)
    register = R.build_register(run_dir, run_id, domain, low_rule)
    for r in register:
        R.validate_row(r)
    texts = {"verdicts.jsonl": _jsonl(rows), "register.jsonl": _jsonl(register),
             "todo.json": json.dumps(T.todo(run_dir, low_rule), indent=1, ensure_ascii=False) + "\n",
             "report.md": report(run_dir, low_rule)}
    return {name: text.encode("utf-8") for name, text in texts.items()}, rows


def merge_run(run_dir, out_dir, run_id, domain, low_rule="confidence-field"):
    files, rows = build_files(run_dir, run_id, domain, low_rule)
    for name, data in files.items():
        (pathlib.Path(out_dir) / name).write_bytes(data)
    return V.counts(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--domain", required=True)
    ap.add_argument("--low-rule", default="confidence-field", choices=V.LOW_RULES)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    print(json.dumps(merge_run(a.run_dir, a.out or a.run_dir, a.run_id, a.domain, a.low_rule)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
