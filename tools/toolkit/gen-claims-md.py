"""Generate a publisher's claims.md (the agent-readable claims page) from an audit run.
Run: python3 -I gen-claims-md.py <audit_dir> <publisher> <domain> <checked_date> <out_file>
<audit_dir> holds claims.jsonl, prove.jsonl, disprove.jsonl and claims.md (for the source hashes).
Status per claim: evidenced | contradicted | no evidence published. 'promise' is set by hand later when the
publisher signs the claim on nuntius under its own key.
"""
import json, sys, pathlib

audit, publisher, domain, checked, out = sys.argv[1:6]
audit = pathlib.Path(audit)

def load(name):
    rows = {}
    for line in (audit / name).read_text().splitlines():
        if line.strip():
            o = json.loads(line)
            rows[o["id"]] = o
    return rows

claims, prove, disprove = load("claims.jsonl"), load("prove.jsonl"), load("disprove.jsonl")
src_rows = [l for l in (audit / "claims.md").read_text().splitlines() if l.startswith("| https://")]

def status(cid):
    if disprove.get(cid, {}).get("contradiction") == "yes":
        return "contradicted"
    if prove.get(cid, {}).get("evidence") == "artefact":
        return "evidenced"
    return "no evidence published"

L = [f"# {publisher}: claims and their evidence", "",
     f"This page lists the checkable claims {domain} makes on its own public surfaces, where each is made, and the evidence",
     "behind it. Verdicts are about evidence on these surfaces only: **evidenced** (an artefact that would be false if the claim",
     "were), **contradicted** (our own surfaces disagree), **no evidence published** (stated, nothing beyond the statement).",
     "Nothing here says true or false. Every proof is a reference plus the sha256 of the bytes it was read from, so anyone can",
     f"re-fetch and compare. Last checked: {checked}. Machine twin of this page: this file.", "",
     "## Sources as fetched", "", "| URL | sha256 |", "|---|---|"]
for r in src_rows:
    cells = [c.strip() for c in r.strip("|").split("|")]
    L.append(f"| {cells[0]} | {cells[4]} |")
L += ["", "## Claims", "", "| id | claim | made at | status | evidence |", "|---|---|---|---|---|"]
for cid, c in claims.items():
    st = status(cid)
    made = "<br>".join(f"{s['url']} ({s['locator']})" for s in c["sources"][:3])
    if st == "evidenced":
        ev = "<br>".join(prove[cid]["refs"][:3])
    elif st == "contradicted":
        ev = "see contradiction: " + "<br>".join(disprove[cid]["refs"][:3])
    else:
        ev = "none yet"
    esc = lambda s: s.replace("|", "\\|")
    L.append(f"| {cid} | {esc(c['claim'])} | {esc(made)} | {st} | {esc(ev)} |")
L += ["", "## How to reply", "",
      f"If you are {publisher} and a line is wrong, answer it: the method page explains how to answer under your own agent key",
      "on nuntius, or write to the address on the contact page. Answers are shown beside the verdict."]
pathlib.Path(out).write_text("\n".join(L) + "\n")
counts = {}
for cid in claims:
    counts[status(cid)] = counts.get(status(cid), 0) + 1
print(json.dumps(counts))
