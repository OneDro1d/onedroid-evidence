"""Turn the lister model's proposals into claims.jsonl (02-sa-data-flow §3, steps 5-8). The model proposes; this decides.

    assemble(previous_claims, sources, proposals, id_high_water) -> {claims, rejects, absent, id_high_water}

proposals = {"new": [{text, kind, checkability}], "reworded": [{prev_id, text}]}.
- Previous claims still published word for word are kept (locate.carry), whatever the model said.
- A rewording must name a previous claim that is no longer published word for word, and must itself be word for word;
  two rewordings of one id keep the one closer to the old text, the other is treated as a new proposal.
- A new claim must be word for word, must not repeat a carried claim, and gets the next id above `id_high_water` (the
  highest id ever issued for the domain, so an absent id is never reused), in source order, then line.
- Anything else is rejected with a reason, never silently listed.
Stdlib only.
"""
import difflib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import locate  # noqa: E402

KINDS = ("capability", "status", "number", "licence", "process", "conduct", "comparison")
CHECKABILITY = ("A", "B", "C")


def _num(cid):
    return int(cid[2:])


def _first_position(text, sources):
    frags = locate.split_fragments(text)
    for i, (_url, s) in enumerate(sources):
        occ = s.locate(frags)
        if occ:
            return (i, occ[0][0])
    for i, (_url, s) in enumerate(sources):
        lines = [s.locate([f]) for f in frags]
        if all(lines):
            return (i, min(found[0][0] for found in lines))
    return (len(sources), 0)


def _text(proposal):
    value = proposal.get("text")
    return value if isinstance(value, str) else ""


def _rows(proposals, key):
    rows = proposals.get(key) if isinstance(proposals, dict) else None
    return rows if isinstance(rows, list) else []


def _is_empty(text):
    return not all(locate.split_fragments(text))


def _not_found_reason(text, sources):
    return "in-excluded-block" if locate.in_excluded_block(text, sources) else "not-verbatim"


def assemble(previous_claims, sources, proposals, id_high_water):
    prev_max = max((_num(c["id"]) for c in previous_claims), default=0)
    if id_high_water < prev_max:
        raise ValueError(f"id_high_water {id_high_water} is below C-{prev_max:03d}, an id already issued")

    carried = locate.carry(previous_claims, sources)
    kept = carried["kept"]
    missing = {c["id"]: c for c in carried["missing"]}
    rejects = []
    listed = {locate.norm_claim(c["claim"]) for c in kept}

    def reject(text, reason):
        rejects.append({"proposed_text": text, "reason": reason})

    candidates = {}
    for r in _rows(proposals, "reworded"):
        if not isinstance(r, dict):
            reject(str(r), "empty")
            continue
        pid, text = r.get("prev_id"), _text(r)
        if not isinstance(pid, str) or pid not in missing:
            reject(text, "not-a-candidate")
            continue
        if _is_empty(text):
            reject(text, "empty")
            continue
        locs = locate.locate_claim(text, sources)
        if not locs:
            reject(text, _not_found_reason(text, sources))
            continue
        ratio = difflib.SequenceMatcher(None, locate.norm_claim(missing[pid]["claim"]), locate.norm_claim(text)).ratio()
        candidates.setdefault(pid, []).append((ratio, text, locs))

    reworded, leftover = [], []
    for pid, cands in candidates.items():
        cands.sort(key=lambda c: -c[0])
        prev = missing[pid]
        for _r, t, _l in cands:
            if locate.norm_claim(t) in listed:
                reject(t, "duplicate")
        free = [c for c in cands if locate.norm_claim(c[1]) not in listed]
        if not free:
            continue
        _ratio, text, locs = free[0]
        leftover += [{"text": t, "kind": prev["kind"], "checkability": prev["checkability"]} for _r, t, _l in free[1:]]
        reworded.append({"id": pid, "claim": text, "sources": locs, "kind": prev["kind"],
                         "checkability": prev["checkability"], "status": "reworded"})
        listed.add(locate.norm_claim(text))

    fresh, seen = [], set()
    for p in _rows(proposals, "new") + leftover:
        if not isinstance(p, dict):
            reject(str(p), "empty")
            continue
        text = _text(p)
        if p.get("kind") not in KINDS:
            reject(text, "bad-kind")
            continue
        if p.get("checkability") not in CHECKABILITY:
            reject(text, "bad-checkability")
            continue
        norm = locate.norm_claim(text)
        if _is_empty(text):
            reject(text, "empty")
            continue
        locs = locate.locate_claim(text, sources)
        if not locs:
            reject(text, _not_found_reason(text, sources))
            continue
        if norm in listed:
            reject(text, "duplicate")
            continue
        if norm in seen:
            continue
        seen.add(norm)
        fresh.append((_first_position(text, sources), text, locs, p["kind"], p["checkability"]))

    fresh.sort(key=lambda f: f[0])
    high = id_high_water
    new_rows = []
    for _pos, text, locs, kind, chk in fresh:
        high += 1
        new_rows.append({"id": "C-%03d" % high, "claim": text, "sources": locs, "kind": kind, "checkability": chk,
                         "status": "new"})

    rewritten = {c["id"] for c in reworded}
    absent = sorted((pid for pid in missing if pid not in rewritten), key=_num)
    claims = sorted(kept + reworded + new_rows, key=lambda c: _num(c["id"]))
    return {"claims": claims, "rejects": rejects, "absent": absent, "id_high_water": high}
