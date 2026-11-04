"""Merge lister + prove + disprove passes into the three-verdict report. Run with python3 -I merge.py <audit_dir> <out_md>."""
import json, sys, pathlib, re, collections

audit = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])

def load(name):
    rows = {}
    for line in (audit / name).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        rows[o["id"]] = o
    return rows

# Optional <audit>/disputed.json, {"C-040": "why it is disputed"}: the ids the disprove summary marked reconcilable or low confidence.
disputed_path = audit / "disputed.json"
DISPUTED = json.loads(disputed_path.read_text()) if disputed_path.exists() else {}
run = json.loads((audit / "run.json").read_text())
PUB, DATE = run["publisher"], str(run["fetched_at"])[:10]

claims = load("claims.jsonl")
prove = load("prove.jsonl")
disprove = load("disprove.jsonl")

missing_p = sorted(set(claims) - set(prove))
missing_d = sorted(set(claims) - set(disprove))

verdicts = {}
for cid, c in claims.items():
    p = prove.get(cid, {"evidence": "none", "refs": [], "note": "prove pass missing"})
    d = disprove.get(cid, {"contradiction": "unverifiable", "refs": [], "note": "disprove pass missing"})
    if d.get("contradiction") == "yes":
        v = "CONTRADICTED"
        if cid in DISPUTED:
            d = dict(d)
            d["note"] = "⚠️ " + DISPUTED[cid] + " " + d.get("note", "")
    elif p.get("evidence") == "artefact":
        v = "EVIDENCED"
    else:
        v = "NO EVIDENCE PUBLISHED"
    sub = []
    if v == "NO EVIDENCE PUBLISHED":
        sub.append("restated only" if p.get("evidence") == "restated" else "nothing beyond the claim")
        if d.get("contradiction") == "unverifiable":
            sub.append("not checkable from the publisher's surfaces")
    verdicts[cid] = (v, ", ".join(sub), p, d)

counts = collections.Counter(v[0] for v in verdicts.values())
by_check = collections.defaultdict(collections.Counter)
for cid, (v, _, _, _) in verdicts.items():
    by_check[claims[cid]["checkability"]][v] += 1

# header: sources table from claims.md
cm = (audit / "claims.md").read_text()
src_rows = [l for l in cm.splitlines() if l.startswith("| https://")]

def esc(s):
    return s.replace("|", "\\|").replace("\n", " ")

def refs(lst, n=3):
    return "<br>".join(esc(r) for r in lst[:n]) if lst else ""

L = []
L.append(f"# Claims audit: {PUB}'s own public claims against {PUB}'s own public evidence ({DATE})")
L.append("")
L.append(f"**What this is.** A claims register for {PUB} ({run['domain']}). A lister agent extracted every checkable claim from the sources below; a prove-it agent")
L.append("looked for the strongest evidence for each on the publisher's own public surfaces (the saved pages, the public repo when there is one, unauthenticated GETs); a")
L.append("disprove-it agent looked for contradictions on the same surfaces. Three verdicts only: **EVIDENCED** (an independent artefact on the publisher's own surfaces would be")
L.append("false if the claim were), **CONTRADICTED** (the publisher's own surfaces disagree with the claim), **NO EVIDENCE PUBLISHED** (the claim is stated, nothing beyond the")
L.append("statement backs it). No verdict says a claim is true or false: outside evidence was not used. Re-run: fetch each source, compare the sha256, re-read the references.")
L.append("")
L.append(f"## Sources (fetched {DATE})")
L.append("")
L.append("| Source URL | Local file | HTTP | Bytes | sha256 |")
L.append("|---|---|---|---|---|")
L.extend(src_rows)
L.append("")
L.append(f"Also read: public repo at `{run.get('repo_commit') or 'none'}`; unauthenticated GETs to the hosts named in run.json: {', '.join(run.get('hosts', []))}.")
L.append("")
L.append("## Result")
L.append("")
L.append("| Verdict | Claims |")
L.append("|---|---|")
for k in ["EVIDENCED", "CONTRADICTED", "NO EVIDENCE PUBLISHED"]:
    L.append(f"| {k} | {counts.get(k, 0)} |")
L.append(f"| total | {len(claims)} |")
L.append("")
L.append("By the lister's checkability class (A = checkable from the pages, B = needs outside evidence or live product access, C = value statement embedding a fact):")
L.append("")
L.append("| Class | EVIDENCED | CONTRADICTED | NO EVIDENCE PUBLISHED |")
L.append("|---|---|---|---|")
for cls in sorted(by_check):
    c = by_check[cls]
    L.append(f"| {cls} | {c.get('EVIDENCED', 0)} | {c.get('CONTRADICTED', 0)} | {c.get('NO EVIDENCE PUBLISHED', 0)} |")
L.append("")
if missing_p or missing_d:
    L.append(f"⚠️ Pass coverage gaps: prove missing {missing_p or 'none'}; disprove missing {missing_d or 'none'}.")
    L.append("")

L.append("## CONTRADICTED (fix these; each quotes both sides)")
L.append("")
L.append("| id | claim | contradiction (disprove pass) | refs |")
L.append("|---|---|---|---|")
for cid, (v, sub, p, d) in verdicts.items():
    if v == "CONTRADICTED":
        L.append(f"| {cid} | {esc(claims[cid]['claim'])} | {esc(d.get('note', ''))} | {refs(d.get('refs', []), 4)} |")
L.append("")
L.append("## NO EVIDENCE PUBLISHED (publish the artefact, reword, or drop)")
L.append("")
L.append("| id | class | claim | why (prove / disprove notes) |")
L.append("|---|---|---|---|")
for cid, (v, sub, p, d) in verdicts.items():
    if v == "NO EVIDENCE PUBLISHED":
        why = f"{sub}. P: {p.get('note', '')} D: {d.get('note', '')}"
        L.append(f"| {cid} | {claims[cid]['checkability']} | {esc(claims[cid]['claim'])} | {esc(why)} |")
L.append("")
L.append("## EVIDENCED (the artefact that backs each)")
L.append("")
L.append("| id | claim | artefact | refs |")
L.append("|---|---|---|---|")
for cid, (v, sub, p, d) in verdicts.items():
    if v == "EVIDENCED":
        L.append(f"| {cid} | {esc(claims[cid]['claim'])} | {esc(p.get('note', ''))} | {refs(p.get('refs', []), 3)} |")
L.append("")
L.append("## Method notes and limits")
L.append("")
L.append("- Three agents (lister, prove, disprove) of one owner. Raw passes: `claims.jsonl`, `prove.jsonl`, `disprove.jsonl` (hashes in the journal).")
L.append("- A claim repeated on several pages is one claim and counts as restated, never as evidence.")
L.append("- The prove pass may grade an artefact that lives outside the pages (a repo path, a live endpoint); those are listed in the EVIDENCED refs so a reader can check without the pages.")
L.append("- Not covered: anything outside the sources above, anything behind a sign-in.")
L.append("- The verdict words are deliberate: nothing here says true or false. Outside evidence would be a second audit.")
L.append("")
out.write_text("\n".join(L) + "\n")
print(json.dumps({"counts": counts, "by_class": {k: dict(v) for k, v in by_check.items()}, "missing_prove": missing_p, "missing_disprove": missing_d}))
