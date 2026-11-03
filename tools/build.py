#!/usr/bin/env python3
"""Compile the evidence site from the repo: every <domain>/index.md -> dist/evidence/ (argus-claims 02-sa-service-map §5).

    python3 -I tools/build.py [--root R] [--out DIR]   build into DIR (default R/dist); refuses a non-empty DIR
    python3 -I tools/build.py [--root R] --check       build twice into temporary folders, then run the invariants

Per domain, from its current run: <domain>.html (tools/toolkit/gen-evidence-page.py with the front-matter flags, the
checked date = the run's fetched_at as a UTC date, the change log = changelog.md), <domain>.md (the landing's
gen-md-twins.py, vendored unchanged), <domain>.json, <domain>.jsonl (register.jsonl byte for byte); and a byte copy of
every run folder under <domain>/runs/ (R-09.3). The build itself refuses a run folder that fails I-4, so the deploy
path never publishes an edited record or a file the run record keeps private (00-overview §4.2); CI is only advisory.

--check runs I-1 (two builds are byte-identical), I-2 (the page, its .md and its .json carry the same (id, verdict, claim
text); .jsonl = register.jsonl), I-4 (each run folder = its manifest.sha256, and only published files) and I-8 (no
secret marker in the tree, the output or the build log, which includes what the generators print). It prints one line
per failure and never the matched text. Stdlib only, deterministic.
"""
import argparse
import atexit
import collections
import contextlib
import datetime
import hashlib
import html.parser
import importlib.util
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.parse

TOOLS = pathlib.Path(__file__).resolve().parent
KIT = TOOLS / "toolkit"
MIN_PYTHON = (3, 11)  # datetime.fromisoformat reading "…Z"; the Vercel build image's python3 is not checked yet (spike S-1)


def python_ok(version=sys.version_info):
    return tuple(version[:2]) >= MIN_PYTHON


if not python_ok():
    sys.exit(f"tools/build.py needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer; this is {sys.version.split()[0]}")

# Toolkit modules are read from source only: Python's bytecode cache lives in a fresh private folder for this process,
# so a .pyc committed under tools/ (an unchecked-hash one is loaded whatever the source says) can't stand in for a
# module. Nothing is written there either.
sys.dont_write_bytecode = True
sys.pycache_prefix = tempfile.mkdtemp(prefix="evidence-build-no-pycache-")
atexit.register(os.rmdir, sys.pycache_prefix)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load("gen_evidence_page", KIT / "gen-evidence-page.py")
TW = _load("gen_md_twins", KIT / "landing-tools" / "gen-md-twins.py")
V = _load("verdict", KIT / "verdict.py")

SCHEMA = "argus-claims/evidence-page@1"
KEYS = ("publisher", "current_run", "self", "split_low_confidence", "certificate_url", "certificate_note")
BOOLS = ("self", "split_low_confidence")
DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
RUN_ID = re.compile(r"^r-[A-Za-z0-9-]+$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
PROMPT = re.compile(r"^method/prompts/([0-9a-f]{64})\.md$")
CLAIM_ID = re.compile(r"^C-[0-9]{3,}$")
# The run-record files that are published (00-overview §4.2), plus the three the importer carries over. Never sources/
# or http-bodies/: third-party bytes, hashes only. manifest.sha256 is checked on its own.
PUBLISHED = frozenset((
    "run.json", "sources.sha256", "http-cache.json", "claims.jsonl", "claims.md", "lister-rejects.jsonl",
    "checks.jsonl", "checks-summary.md", "prove.jsonl", "disprove.jsonl", "tool-fetches.json", "verdicts.jsonl",
    "register.jsonl", "todo.json", "report.md", "gates.json", "MOVEMENT.md", "movement.json", "model-calls.jsonl",
    "judge.json", "private-evidence.json", "prove-summary.md", "disprove-summary.md"))
# Joined at run time so neither this file nor its bytecode cache carries a whole marker.
MARKERS = tuple("".join(p).encode() for p in (("sk-", "ant-"), ("gh", "s_"), ("gh", "p_"), ("github", "_pat_"),
                                               ("-----", "BEGIN")))
SECTION_VERDICT = {"contradicted": "contradicted", "contradicted-low-confidence": "contradicted_low",
                   "evidenced": "evidenced", "no-evidence-published": "no_evidence_published",
                   "evidence-private": "evidence_private"}
HEADING_VERDICT = {"Contradicted": "contradicted", "Contradicted, low confidence": "contradicted_low",
                   "Evidenced": "evidenced", "No evidence published": "no_evidence_published",
                   "Evidence private": "evidence_private"}
MD_HEADING = re.compile(r"^## (.+) \([0-9]+\)$")
MD_ROW = re.compile(r"^(C-[0-9]{3,}) \| (.*)$")


class BuildError(Exception):
    """A tree the compiler refuses; the message names the file."""


def _has_marker(text):
    data = text.encode("utf-8", "replace") if isinstance(text, str) else text
    return any(m in data for m in MARKERS)


def _withheld(line):
    """A report line, unless it carries a secret marker: then only its first word and a note."""
    return f"{line.split(' ', 1)[0]} (message withheld: it carries a secret marker)" if _has_marker(line) else line


def front_matter(path):
    """The flat `key: value` lines between the two --- lines at the top of <domain>/index.md (02-sa-data-model §6)."""
    path = pathlib.Path(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    fences = [n for n, line in enumerate(lines) if line.strip() == "---"]
    if len(fences) < 2 or fences[0] != 0:
        raise BuildError(f"{path}: no front matter between two --- lines at the top")
    meta = {}
    for n in range(1, fences[1]):
        line = lines[n]
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not sep:
            raise BuildError(f"{path}:{n + 1}: not a key: value line")
        if key not in KEYS:
            raise BuildError(f"{path}:{n + 1}: unknown key {key}")
        if key in meta:
            raise BuildError(f"{path}:{n + 1}: {key} given twice")
        if key in BOOLS:
            if value not in ("true", "false"):
                raise BuildError(f"{path}:{n + 1}: {key} must be true or false")
            value = value == "true"
        meta[key] = value
    for key in ("publisher", "current_run"):
        if not meta.get(key):
            raise BuildError(f"{path}: {key} is required")
    if not RUN_ID.match(meta["current_run"]):
        raise BuildError(f"{path}: current_run {meta['current_run']!r} is not a run id")
    if meta.get("certificate_note") and not meta.get("certificate_url"):
        raise BuildError(f"{path}: certificate_note needs certificate_url")
    return {"publisher": meta["publisher"], "current_run": meta["current_run"],
            "self": meta.get("self", False), "split_low_confidence": meta.get("split_low_confidence", False),
            "certificate_url": meta.get("certificate_url") or None, "certificate_note": meta.get("certificate_note") or None}


def _domain_dirs(root):
    """Every top-level entry named like a domain, symlinks included (domains() refuses them; nothing follows them)."""
    return [p for p in sorted(pathlib.Path(root).iterdir()) if DOMAIN.match(p.name) and (p.is_symlink() or p.is_dir())]


def domains(root):
    """[(domain, front matter, current run folder)], every domain checked before anything is written."""
    out = []
    for d in _domain_dirs(root):
        if d.is_symlink():
            raise BuildError(f"{d}: a domain folder that is a symlink")
        for p in sorted(d.rglob("*")):
            if p.is_symlink():
                raise BuildError(f"{p}: a symlink in a domain folder")
        if not (d / "index.md").is_file():
            raise BuildError(f"{d.name}: a domain folder with no index.md")
        meta = front_matter(d / "index.md")
        run = d / "runs" / meta["current_run"]
        if not run.is_dir():
            raise BuildError(f"{d / 'index.md'}: current_run {meta['current_run']} has no folder under runs/")
        out.append((d.name, meta, run))
    return out


def _run_folders(domain_dir):
    runs = domain_dir / "runs"
    return sorted(p for p in runs.iterdir() if p.is_dir()) if runs.is_dir() and not runs.is_symlink() else []


def run_folder_problems(folder, rel):
    """I-4 for one run folder: flat, only published files, and equal to its manifest.sha256 (sorted, each file once)."""
    problems, manifest = [], folder / "manifest.sha256"
    present = {}
    for p in sorted(folder.rglob("*")):
        name = p.relative_to(folder).as_posix()
        if p.is_symlink():
            problems.append(f"{rel}/{name}: a symlink")
        elif p.is_dir():
            problems.append(f"{rel}/{name}: a subfolder (a run folder is flat)")
        elif p != manifest:
            present[name] = p
            if name not in PUBLISHED:
                problems.append(f"{rel}/{name}: not a published run-record file (00-overview §4.2)")
    if not manifest.is_file() or manifest.is_symlink():
        return problems + [f"{rel}/manifest.sha256: missing"]
    try:
        text = manifest.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return problems + [f"{rel}/manifest.sha256: not UTF-8"]
    listed, order = {}, []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        sha, sep, name = line.partition("  ")
        path = pathlib.PurePosixPath(name)
        if not sep or not HEX64.match(sha) or not name:
            problems.append(f"{rel}/manifest.sha256:{n}: not a hash and a path")
        elif path.is_absolute() or ".." in path.parts:
            problems.append(f"{rel}/manifest.sha256:{n}: {name} is outside the run folder")
        elif name in listed:
            problems.append(f"{rel}/{name}: listed twice in manifest.sha256")
        else:
            listed[name] = sha
            order.append(name)
    if order != sorted(order):
        problems.append(f"{rel}/manifest.sha256: lines not sorted by path")
    for name in sorted(set(listed) | set(present)):
        if name not in present:
            problems.append(f"{rel}/{name}: listed in manifest.sha256 but missing")
        elif name not in listed:
            problems.append(f"{rel}/{name}: not listed in manifest.sha256")
        elif hashlib.sha256(present[name].read_bytes()).hexdigest() != listed[name]:
            problems.append(f"{rel}/{name}: does not match manifest.sha256")
    return problems


def checked_date(run):
    """The run's fetched_at as a UTC date. A time without a zone, or not a real time, fails the build."""
    path = run / "run.json"
    fetched = json.loads(path.read_text(encoding="utf-8")).get("fetched_at") if path.is_file() else None
    try:
        when = datetime.datetime.fromisoformat(fetched)
    except (TypeError, ValueError):
        when = None
    if when is None or when.tzinfo is None:
        raise BuildError(f"{path}: fetched_at is not a time with a zone")
    return when.astimezone(datetime.timezone.utc).date().isoformat()


def page_html(run, domain, meta, checked, changelog):
    page, _counts = G.build(run, meta["publisher"], domain, checked, self_mode=meta["self"],
                            split_low=meta["split_low_confidence"], certificate_url=meta["certificate_url"],
                            certificate_note=meta["certificate_note"], changelog_entries=changelog)
    return page


def _twin(out, rel_html, url):
    """The landing's own twin of a built page (its ROOT is the build folder; nothing else changes)."""
    TW.ROOT = pathlib.Path(out)
    return TW.render(rel_html, url)


def render_twin(out, domain):
    return _twin(out, f"evidence/{domain}.html", f"/evidence/{domain}")


def _register(run):
    return [json.loads(line) for line in (run / "register.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def page_json(domain, meta, run, checked):
    claims = _register(run)
    verdicts = collections.Counter(c["verdict"] for c in claims)
    return {"schema": SCHEMA, "domain": domain, "publisher": meta["publisher"], "run_id": meta["current_run"],
            "checked": checked,
            "counts": {"total": len(claims), "evidenced": verdicts["evidenced"], "contradicted": verdicts["contradicted"],
                       "low_confidence": sum(c.get("confidence") == "low" for c in claims),
                       "no_evidence_published": verdicts["no_evidence_published"],
                       "evidence_private": verdicts["evidence_private"]},
            "claims": claims,
            "sources": [{"url": cells[0], "sha256": cells[4]} for cells in G.source_rows(run)]}


def page_jsonl(run):
    return (run / "register.jsonl").read_bytes()


SITE = "https://onedroid.ai"
WORDS = {"evidenced": "evidenced", "contradicted": "contradicted", "no_evidence_published": "no evidence published",
         "evidence_private": "evidence private", "withdrawn": "withdrawn"}


def _site_header():
    """The landing's header and nav, exactly as the register pages carry them (taken from gen_evidence_page.head)."""
    stub = {"EVIDENCED": 0, "CONTRADICTED": 0, "NO EVIDENCE PUBLISHED": 0}
    return G.head("-", "-", "-", stub, 0).split("<body>\n", 1)[1]


def _ld(data):
    """JSON-LD for a <script> block; '<' escaped so text can never close the block."""
    return json.dumps(data, indent=2, ensure_ascii=False).replace("<", "\\u003c")


def _page(title, desc, path, md_path, body, ld=None):
    e = G.e
    ld_block = f'\n  <script type="application/ld+json">\n{_ld(ld)}\n  </script>' if ld else ""
    return (f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{e(title)} — OneDroid evidence</title>
  <meta name="description" content="{e(desc)}">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <link rel="canonical" href="{SITE}{path}">
  <link rel="alternate" type="text/markdown" href="{SITE}{md_path}">
  <meta property="og:type" content="article">
  <meta property="og:title" content="{e(title)}">
  <meta property="og:description" content="{e(desc)}">
  <meta property="og:url" content="{SITE}{path}">
  <meta property="og:image" content="https://onedroid.ai/assets/og-wordmark.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/styles.css">{ld_block}
</head>
<body>
""" + _site_header() + body + G.FOOTER)


def _section(heading, inner, anchor=None):
    a = f' id="{G.e(anchor)}"' if anchor else ""
    return f"""
  <section class="section"{a}>
    <div class="container">
      <h2>{G.e(heading)}</h2>
      {inner}
    </div>
  </section>
"""


def _table(header, rows):
    head = "".join(f"<th>{G.e(h)}</th>" for h in header)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<div class="cs-table-wrap"><table class="cs-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _link(url):
    """A link only for an http(s) URL; anything else (javascript:, data:, a bare word) is shown as text."""
    return f'<a href="{G.e(url)}">{G.e(url)}</a>' if re.match(r"^https?://", str(url), re.I) else G.e(url)


def _md_text(text):
    """Text for Markdown link text the build writes itself: backslash and brackets escaped, one line."""
    return " ".join(str(text).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").split())


def _hero(eyebrow, heading, text, back=True):
    link = '\n      <a class="back-link" href="/evidence">Evidence pages</a>' if back else ""
    return f"""
  <section class="page-hero">
    <div class="container">{link}
      <p class="eyebrow">{eyebrow}</p>
      <h1>{heading}</h1>
      <p class="hero-sub">{text}</p>
    </div>
  </section>
"""


def _counts(rows):
    verdicts = collections.Counter(c["verdict"] for c in rows)
    return {"total": len(rows), "evidenced": verdicts["evidenced"], "contradicted": verdicts["contradicted"],
            "low_confidence": sum(c.get("confidence") == "low" for c in rows),
            "no_evidence_published": verdicts["no_evidence_published"], "evidence_private": verdicts["evidence_private"]}


def _counts_cells(counts):
    contradicted = f"{counts['contradicted']}" + (f" ({counts['low_confidence']} low confidence)" if counts["low_confidence"] else "")
    none = f"{counts['no_evidence_published']}" + (f"; {counts['evidence_private']} evidence private" if counts["evidence_private"] else "")
    return [str(counts["total"]), str(counts["evidenced"]), contradicted, none]


def _fetched(folder):
    path = folder / "run.json"
    fetched = json.loads(path.read_text(encoding="utf-8")).get("fetched_at") if path.is_file() else None
    try:
        when = datetime.datetime.fromisoformat(fetched)
    except (TypeError, ValueError):
        when = None
    if when is None or when.tzinfo is None:
        raise BuildError(f"{path}: fetched_at is not a time with a zone")
    return when.astimezone(datetime.timezone.utc)


def _record_rows(path):
    """id -> row of a run's JSON lines; every id a claim id (it becomes a file name), the file present."""
    if not path.is_file():
        raise BuildError(f"{path}: missing")
    try:
        rows = _object_rows(path)
    except (UnicodeDecodeError, ValueError):
        raise BuildError(f"{path}: not JSON lines of objects") from None
    for r in rows:
        if _id_number(r.get("id")) < 0:
            raise BuildError(f"{path}: {r.get('id')!r} is not a claim id")
    return {r["id"]: r for r in rows}


def history(domain_dir):
    """Every run of a domain, oldest first: {run_id, checked, register (id -> row, claims order), verdicts, claims,
    judge, movement}. Refuses what would make a wrong page: a run folder that is not a run id, a missing record file, an
    id that is not C-nnn, a claim neither registered nor withdrawn."""
    for folder in _run_folders(domain_dir):
        if not RUN_ID.match(folder.name):
            raise BuildError(f"{folder}: not a run id")
    runs = []
    for folder in sorted(_run_folders(domain_dir), key=lambda f: (_fetched(f), f.name)):
        judge = folder / "judge.json"
        movement = folder / "movement.json"
        run = {"run_id": folder.name, "checked": _fetched(folder).date().isoformat(),
               "register": _record_rows(folder / "register.jsonl"), "verdicts": _record_rows(folder / "verdicts.jsonl"),
               "claims": _record_rows(folder / "claims.jsonl"),
               "judge": json.loads(judge.read_text(encoding="utf-8")) if judge.is_file() else {},
               "movement": json.loads(movement.read_text(encoding="utf-8")) if movement.is_file() else None}
        for cid in run["claims"]:
            if cid not in run["register"] and not run["verdicts"].get(cid, {}).get("withdrawn"):
                raise BuildError(f"{folder}: {cid} is neither in the register nor withdrawn")
        runs.append(run)
    return runs


def runs_json(domain, meta, runs):
    return {"schema": "argus-claims/runs@1", "domain": domain, "publisher": meta["publisher"], "current_run": meta["current_run"],
            "runs": [{"run_id": r["run_id"], "checked": r["checked"], "current": r["run_id"] == meta["current_run"],
                      "counts": _counts(list(r["register"].values())),
                      "movement": {k: len(r["movement"][k]) for k in ("kept", "reworded", "new", "absent")} if r["movement"] else None,
                      "record": f"/evidence/{domain}/runs/{r['run_id']}/manifest.sha256"} for r in reversed(runs)]}


def runs_html(domain, meta, data):
    e = G.e
    rows = []
    for r in data["runs"]:
        m = r["movement"]
        moved = "first run" if m is None else f"{m['kept']} kept, {m['reworded']} reworded, {m['new']} new, {m['absent']} absent"
        rows.append([e(r["run_id"]) + (" (current)" if r["current"] else ""), e(r["checked"]), *_counts_cells(r["counts"]),
                     e(moved), f'<a href="{e(r["record"])}">manifest.sha256</a>'])
    body = (_hero(f"Evidence page · {e(domain)} · run history", f"{e(meta['publisher'])}: every run of its register.",
                  f'Each run of the register for <a href="/evidence/{e(domain)}">{e(domain)}</a>, newest first, with its counts, what '
                  "moved against the run before it, and the published record, file by file, under its manifest.")
            + _section("Runs", _table(["Run", "Checked", "Claims", "Evidenced", "Contradicted", "No evidence published",
                                       "Movement", "Record"], rows), "runs"))
    return _page(f"{meta['publisher']}: run history", f"Every run of the {domain} claims register, with counts and movement.",
                 f"/evidence/{domain}/runs", f"/evidence/{domain}/runs.md", body)


def claim_json(domain, meta, runs, cid):
    current = next((r for r in runs if r["run_id"] == meta["current_run"]), None)
    listed = [r for r in runs if cid in r["claims"]]
    entries = []
    for r in reversed(listed):
        row, claim = r["register"].get(cid), r["claims"][cid]
        if row is not None:
            entry = {"run_id": r["run_id"], "checked": r["checked"], "text": row["text"], "verdict": row["verdict"]}
            if "confidence" in row:
                entry["confidence"] = row["confidence"]
            entry["ruled"] = row["ruled"]
            source, locator, sha, refs = row["source"], row["locator"], row["sha256"], row["refs"]
        else:  # withdrawn: not in the register
            first = (claim.get("sources") or [{}])[0]
            entry = {"run_id": r["run_id"], "checked": r["checked"], "text": claim["claim"], "verdict": "withdrawn",
                     "ruled": bool(r["verdicts"].get(cid, {}).get("ruled", True))}
            source, locator, sha, refs = first.get("url"), first.get("locator"), None, []
        if r["judge"].get(cid, {}).get("note"):
            entry["note"] = r["judge"][cid]["note"]
        entry.update({"source": source, "locator": locator, "sha256": sha, "refs": refs})
        entries.append(entry)
    if current is not None and cid in current["register"]:
        status = "current"
    elif current is not None and cid in current["claims"]:
        status = "withdrawn in the current run"
    else:
        status = f"retired after {listed[-1]['run_id']}"
    return {"schema": "argus-claims/claim@1", "domain": domain, "id": cid, "status": status,
            "first_seen": listed[0]["run_id"], "last_seen": listed[-1]["run_id"], "runs": entries}


def claim_html(domain, meta, data):
    e, cid = G.e, data["id"]
    rows = []
    for x in data["runs"]:
        verdict = WORDS.get(x["verdict"], x["verdict"]) + (" (low confidence)" if x.get("confidence") == "low" else "")
        verdict += " · ruled by the reviewer" if x["ruled"] and x["verdict"] != "withdrawn" else ""
        refs = "<br>".join(e(f"{r.get('pass', '')}: {r['ref']}" + (f' "{r["quote"]}"' if r.get("quote") else "")) for r in x["refs"])
        made = f'{_link(x["source"] or "")} ({e(x["locator"])})' + (f'<br>sha256 <code>{e(x["sha256"])}</code>' if x["sha256"] else "")
        note = f"<br><em>Reviewer's note: {e(x['note'])}</em>" if x.get("note") else ""
        rows.append([e(x["run_id"]), e(x["checked"]), e(x["text"]), e(verdict) + note, made, refs])
    back = (f' It is row <a href="/evidence/{e(domain)}#{e(cid)}">{e(cid)}</a> of the current register.'
            if data["status"] == "current" else "")
    day = {x["run_id"]: x["checked"] for x in data["runs"]}
    body = (_hero(f"Evidence page · {e(domain)} · claim {e(cid)}", f"{e(cid)}: one claim of {e(meta['publisher'])}, run by run.",
                  f"Status: {e(data['status'])}. First seen {e(day[data['first_seen']])}, last seen {e(day[data['last_seen']])}.{back} "
                  f'All runs: <a href="/evidence/{e(domain)}/runs">run history</a>. Nothing here says the claim is true or false.')
            + _section("Every run that lists it", _table(["Run", "Checked", "Claim, as made", "Verdict", "Made at", "References"], rows), "runs"))
    newest = data["runs"][0]
    ld = {"@context": "https://schema.org", "@type": "Claim", "text": newest["text"], "appearance": newest["source"],
          "author": {"@type": "Organization", "name": meta["publisher"], "url": f"https://{domain}"}}
    return _page(f"{cid} · {meta['publisher']} ({domain})", f"Claim {cid} of {meta['publisher']} ({domain}), its verdict and references in every run.",
                 f"/evidence/{domain}/{cid}", f"/evidence/{domain}/{cid}.md", body, ld)


def index_json(entries):
    return {"schema": "argus-claims/index@1", "registers": [{
        "domain": d, "publisher": meta["publisher"], "run_id": meta["current_run"], "checked": checked, "counts": counts,
        "links": {"page": f"/evidence/{d}", "md": f"/evidence/{d}.md", "json": f"/evidence/{d}.json",
                  "jsonl": f"/evidence/{d}.jsonl", "runs": f"/evidence/{d}/runs"}} for d, meta, checked, counts in entries]}


def index_html(data):
    e = G.e
    rows = [[f'<a href="{e(r["links"]["page"])}">{e(r["publisher"])}</a> ({e(r["domain"])})', e(r["checked"]),
             *_counts_cells(r["counts"]),
             f'<a href="{e(r["links"]["md"])}">.md</a> · <a href="{e(r["links"]["json"])}">.json</a> · '
             f'<a href="{e(r["links"]["jsonl"])}">.jsonl</a> · <a href="{e(r["links"]["runs"])}">runs</a>'] for r in data["registers"]]
    body = (_hero("Evidence pages", "What a company's site claims, <br>and what the company has published that backs it.",
                  "Each page below lists the checkable claims one company makes on its own public pages, where each claim is made, "
                  "and the evidence the company itself has published for it. Nothing on these pages says a claim is true or false.",
                  back=False)
            + _section("The pages", _table(["Company", "Checked", "Claims", "Evidenced", "Contradicted", "No evidence published",
                                            "Also as"], rows), "pages"))
    return _page("Evidence pages — what a company's site claims, and what backs it",
                 "For each listed company: every checkable claim its own public pages make and the evidence it has published.",
                 "/evidence", "/evidence/index.md", body)


def llms_txt(data):
    lines = ["# OneDroid evidence pages", "",
             "> Registers of the checkable claims companies make on their own public pages, with the evidence each company "
             "has published. Nothing here says true or false.", "", "## Registers", ""]
    lines += [f"- [{_md_text(r['publisher'])} ({r['domain']})]({SITE}{r['links']['md']}): checked {r['checked']}, "
              f"{r['counts']['total']} claims" for r in data["registers"]]
    lines += ["", "## Run history", ""]
    lines += [f"- [{_md_text(r['publisher'])} ({r['domain']}): runs]({SITE}{r['links']['runs']}.md)" for r in data["registers"]]
    return "\n".join(lines) + "\n"


def sitemap_xml(pages):
    from xml.sax.saxutils import escape
    urls = "".join(f"  <url><loc>{escape(SITE + path)}</loc>" + (f"<lastmod>{escape(day)}</lastmod>" if day else "") + "</url>\n"
                   for path, day in sorted(pages.items()))
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n'


def _inside(out, rel):
    """out/rel, refusing any path that would land outside the output folder."""
    path = pathlib.Path(out) / rel
    if not path.resolve().is_relative_to(pathlib.Path(out).resolve()):
        raise BuildError(f"{rel}: outside the output folder")
    return path


def build(root, out):
    """Write the site into `out` and return the build log: one line per page and per copied run folder, then every
    line the generators printed (captured, so the caller decides whether it may be shown)."""
    root, out = pathlib.Path(root), pathlib.Path(out)
    if out.exists() and any(out.iterdir()):
        raise BuildError(f"{out} is not empty")
    found = domains(root)
    problems = [p for domain, _meta, _run in found for folder in _run_folders(root / domain)
                for p in run_folder_problems(folder, f"{domain}/runs/{folder.name}")]
    if problems:
        raise BuildError("; ".join(problems))
    histories = {domain: history(root / domain) for domain, _meta, _run in found}  # every record checked before a write
    log, printed = [], io.StringIO()

    def write(rel, data):
        path = _inside(out, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return len(data)

    def emit(rel, make):
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
            data = make()
        log.append(f"wrote {rel} {write(rel, data if isinstance(data, bytes) else data.encode('utf-8'))} B")

    def as_json(data):
        return json.dumps(data, indent=1, ensure_ascii=False) + "\n"

    def page_set(stem, make_html, data, url):  # the HTML first: the twin is made from it
        emit(f"{stem}.html", make_html)
        emit(f"{stem}.md", lambda: _twin(out, f"{stem}.html", url))
        emit(f"{stem}.json", lambda: as_json(data))

    index_entries, register_md, sitemap = [], [], {}
    for domain, meta, run in found:
        checked = checked_date(run)
        changelog = root / domain / "changelog.md"
        entries = G.read_changelog(changelog) if changelog.is_file() else None
        register = page_json(domain, meta, run, checked)
        emit(f"evidence/{domain}.html", lambda: page_html(run, domain, meta, checked, entries))
        emit(f"evidence/{domain}.md", lambda: render_twin(out, domain))
        emit(f"evidence/{domain}.json", lambda: as_json(page_json(domain, meta, run, checked)))
        emit(f"evidence/{domain}.jsonl", lambda: page_jsonl(run))
        for folder in _run_folders(root / domain):
            files = [f for f in sorted(folder.iterdir()) if f.is_file()]
            for f in files:
                write(f"evidence/{domain}/runs/{folder.name}/{f.name}", f.read_bytes())
            log.append(f"copied evidence/{domain}/runs/{folder.name}/ {len(files)} files")
        runs = histories[domain]
        dates = {r["run_id"]: r["checked"] for r in runs}
        rj = runs_json(domain, meta, runs)
        page_set(f"evidence/{domain}/runs", lambda: runs_html(domain, meta, rj), rj, f"/evidence/{domain}/runs")
        for cid in sorted({c for r in runs for c in r["claims"]}, key=lambda c: (_id_number(c), str(c))):
            cj = claim_json(domain, meta, runs, cid)
            page_set(f"evidence/{domain}/{cid}", lambda: claim_html(domain, meta, cj), cj, f"/evidence/{domain}/{cid}")
            sitemap[f"/evidence/{domain}/{cid}"] = dates[cj["last_seen"]]
        sitemap[f"/evidence/{domain}"] = checked
        sitemap[f"/evidence/{domain}/runs"] = max(dates.values())
        index_entries.append((domain, meta, checked, register["counts"]))
        register_md.append((out / "evidence" / f"{domain}.md").read_text(encoding="utf-8"))
    ij = index_json(index_entries)
    page_set("evidence/index", lambda: index_html(ij), ij, "/evidence")
    sitemap["/evidence"] = max([day for _d, _m, day, _c in index_entries], default=None)
    emit("evidence/llms.txt", lambda: llms_txt(ij))
    emit("evidence/llms-full.txt", lambda: "\n".join(register_md))
    emit("evidence/sitemap.xml", lambda: sitemap_xml(sitemap))
    return log + [f"generator: {line}" for line in printed.getvalue().splitlines()]


def _files(base, skip=()):
    """Every regular file under base, sorted, never following a symlink; `skip` names folders left out at the top only."""
    for dirpath, dirnames, filenames in os.walk(base):
        top = pathlib.Path(dirpath) == pathlib.Path(base)
        dirnames[:] = sorted(d for d in dirnames if not (top and d in skip))
        for name in sorted(filenames):
            path = pathlib.Path(dirpath) / name
            if path.is_file() and not path.is_symlink():
                yield path


def _norm(text):
    return " ".join(text.split())


class _PageRows(html.parser.HTMLParser):
    """(id, verdict, claim text) for every <tr id="C-nnn">: the verdict from its section's id, the text from its 2nd cell."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.section, self.row, self.cells = [], None, None, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section":
            self.section = a.get("id")
        elif tag == "tr" and CLAIM_ID.match(a.get("id") or ""):
            self.row, self.cells = a["id"], []
        elif tag == "td" and self.row:
            self.cells.append([])

    def handle_endtag(self, tag):
        if tag == "tr" and self.row:
            text = "".join(self.cells[1]) if len(self.cells) > 1 else ""
            self.rows.append((self.row, SECTION_VERDICT.get(self.section, f"outside a verdict section ({self.section})"),
                              _norm(text)))
            self.row = None

    def handle_data(self, data):
        if self.row and self.cells:
            self.cells[-1].append(data)


def html_rows(text):
    parser = _PageRows()
    parser.feed(text)
    parser.close()
    return parser.rows


def md_rows(text):
    """(id, verdict, row text) for every `C-nnn | …` row under a verdict heading of the twin. A row runs to the next
    blank line; its text is everything after the id, so it starts with the claim (which may itself hold ' | ')."""
    rows, verdict, current = [], None, None
    for line in text.split("\n"):
        heading = MD_HEADING.match(line)
        if heading or line.startswith("## "):
            verdict, current = (HEADING_VERDICT.get(heading.group(1)) if heading else None), None
            continue
        row = MD_ROW.match(line)
        if row and verdict:
            current = [row.group(1), verdict, row.group(2)]
            rows.append(current)
        elif current is not None and line.strip():
            current[2] += " " + line
        else:
            current = None
    return [(cid, v, _norm(t)) for cid, v, t in rows]


def _same(mine, page):
    return mine == page


def _starts_the_row(mine, page):
    """The twin's row text begins with the page's claim text and then the next cell."""
    return mine.startswith(page + " |")


def _compare(rel, rows, page, same=_same):
    failures = [f"I-2 {rel}: {cid} listed {n} times" for cid, n in sorted(collections.Counter(r[0] for r in rows).items()) if n > 1]
    mine = {cid: (verdict, text) for cid, verdict, text in rows}
    for cid in sorted(set(mine) | set(page)):
        if cid not in mine:
            failures.append(f"I-2 {rel}: {cid} is on the page and missing here")
        elif cid not in page:
            failures.append(f"I-2 {rel}: {cid} is here and not on the page")
        elif mine[cid][0] != page[cid][0]:
            failures.append(f"I-2 {rel}: {cid} reads {mine[cid][0]}, the page reads {page[cid][0]}")
        elif not same(mine[cid][1], page[cid][1]):
            failures.append(f"I-2 {rel}: {cid} claim text differs from the page")
    return failures


def _json_verdict(claim, split_low):
    """A contradiction marked low confidence is its own verdict where the page shows it in its own section."""
    verdict = claim.get("verdict")
    return "contradicted_low" if split_low and verdict == "contradicted" and claim.get("confidence") == "low" else verdict


def parity(root, out):
    """I-2 (VR-09) over every domain of a finished build."""
    failures = []
    for domain, meta, run in domains(root):
        base = out / "evidence"
        page_rows = html_rows((base / f"{domain}.html").read_text(encoding="utf-8"))
        failures += [f"I-2 evidence/{domain}.html: {cid} listed {n} times"
                     for cid, n in sorted(collections.Counter(r[0] for r in page_rows).items()) if n > 1]
        page = {cid: (verdict, text) for cid, verdict, text in page_rows}
        failures += _compare(f"evidence/{domain}.md", md_rows((base / f"{domain}.md").read_text(encoding="utf-8")), page,
                             _starts_the_row)
        claims = json.loads((base / f"{domain}.json").read_text(encoding="utf-8")).get("claims", [])
        failures += _compare(f"evidence/{domain}.json",
                             [(c.get("id"), _json_verdict(c, meta["split_low_confidence"]), _norm(str(c.get("text", ""))))
                              for c in claims], page)
        if (base / f"{domain}.jsonl").read_bytes() != (run / "register.jsonl").read_bytes():
            failures.append(f"I-2 evidence/{domain}.jsonl: not register.jsonl byte for byte")
    return failures


class _Links(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs, self.ids = [], set()

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key == "href" and value is not None:
                self.hrefs.append(value)
            elif key == "id" and value is not None:
                self.ids.add(value)


def cited_urls(root):
    """{domain: every URL its runs cite as a source (claims.jsonl sources, the claims.md table)}: data, which I-7 leaves
    alone on that domain's own pages only."""
    cited = collections.defaultdict(set)
    for d, folder in _run_dirs(root):
        if (folder / "claims.jsonl").is_file():
            for row in _jsonl_rows(folder / "claims.jsonl"):
                cited[d.name].update(s.get("url") for s in row.get("sources", []) if isinstance(s, dict) and s.get("url"))
        if (folder / "claims.md").is_file():
            cited[d.name].update(cells[0] for cells in G.source_rows(folder))
    return dict(cited)


def _page_domain(rel):
    """The domain a built page belongs to (evidence/<d>.html, evidence/<d>/...), or None (index, llms, ...)."""
    parts = rel.split("/")
    name = parts[1][:-len(".html")] if len(parts) == 2 and parts[1].endswith(".html") else (parts[1] if len(parts) > 2 else "")
    return name if DOMAIN.match(name) else None


def links(out, cited=None):
    """I-7: in every built page, each link on onedroid.ai (any case, www., any port) resolves: /evidence paths to a built
    file (and its #id to an id there), any other path to a line of tools/tests/landing-paths.txt. A URL the page's own
    domain cites as a source is data and is not checked there; other hosts and mailto: are not checked here."""
    out, cited = pathlib.Path(out), cited or {}
    landing = {line.strip() for line in (TOOLS / "tests" / "landing-paths.txt").read_text(encoding="utf-8").splitlines() if line.strip()}
    parsed = {}
    for p in sorted(out.rglob("*.html")):
        parser = _Links()
        parser.feed(p.read_text(encoding="utf-8"))
        parser.close()
        parsed[p.relative_to(out).as_posix()] = parser

    def url_of(rel):
        path = "/" + rel[:-len(".html")]
        return "/evidence" if path == "/evidence/index" else path

    def target(path):
        if path == "/evidence":
            return "evidence/index.html"
        if not path.startswith("/evidence/"):
            return None
        if f"{path[1:]}.html" in parsed:
            return f"{path[1:]}.html"
        return path[1:] if (out / path[1:]).is_file() else None

    failures = set()
    for rel, parser in parsed.items():
        own = cited.get(_page_domain(rel), set())
        for href in parser.hrefs:
            full = urllib.parse.urljoin(SITE + url_of(rel), href)
            parts = urllib.parse.urlsplit(full)
            if parts.scheme not in ("http", "https") or parts.hostname not in ("onedroid.ai", "www.onedroid.ai"):
                continue
            if href in own or full.split("#", 1)[0] in own:
                continue
            path, hit = parts.path or "/", target(parts.path or "/")
            if hit is None and path not in landing:
                on_site = path == "/evidence" or path.startswith("/evidence/")
                failures.add(f"I-7 {rel}: {href} " + ("does not resolve" if on_site else "is not a built page or a landing path"))
            elif hit is not None and parts.fragment and parts.fragment not in getattr(parsed.get(hit), "ids", set()):
                failures.add(f"I-7 {rel}: {href} has no such anchor")
    return sorted(failures)


def determinism(a, b):
    """I-1: two builds of the same tree, byte for byte."""
    fa = {p.relative_to(a).as_posix(): p.read_bytes() for p in _files(a)}
    fb = {p.relative_to(b).as_posix(): p.read_bytes() for p in _files(b)}
    return [f"I-1 {rel}: differs between two builds" for rel in sorted(set(fa) | set(fb)) if fa.get(rel) != fb.get(rel)]


def manifests(root):
    """I-4 over every run folder of every domain, current or not."""
    failures = []
    for d in _domain_dirs(root):
        if d.is_symlink():
            failures.append(f"I-4 {d.name}: a domain folder that is a symlink (not followed)")
            continue
        failures += [f"I-4 {p}" for folder in _run_folders(d) for p in run_folder_problems(folder, f"{d.name}/runs/{folder.name}")]
    return failures


def _id_number(cid):
    """C-nnn as a number (ids start at C-001); -1 for anything else."""
    return int(cid[2:]) if isinstance(cid, str) and CLAIM_ID.match(cid) and int(cid[2:]) >= 1 else -1


def _jsonl_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _run_dirs(root):
    """(domain folder, run folder) for every run of every domain folder that is not a symlink."""
    return [(d, folder) for d in _domain_dirs(root) if not d.is_symlink() for folder in _run_folders(d)]


REGISTER_WORD = {"EVIDENCED": "evidenced", "CONTRADICTED": "contradicted",
                 "NO EVIDENCE PUBLISHED": "no_evidence_published", "EVIDENCE PRIVATE": "evidence_private"}


def _object_rows(path):
    rows = _jsonl_rows(path)
    if not all(isinstance(r, dict) for r in rows):
        raise ValueError("a row that is not an object")
    return rows


def _record_rule(folder):
    """The low-confidence rule a record was made under: note-text for an imported run, confidence-field otherwise."""
    meta = json.loads((folder / "run.json").read_text(encoding="utf-8")) if (folder / "run.json").is_file() else {}
    return "note-text" if meta.get("imported") is True else "confidence-field"


def verdict_recompute(root):
    """I-3 (VR-09): in every run folder, verdict.py over the passes (+ judge.json, private-evidence.json) with the
    record's rule equals verdicts.jsonl row for row, and register.jsonl agrees with it."""
    failures = []
    for d, folder in _run_dirs(root):
        rel = f"{d.name}/runs/{folder.name}/verdicts.jsonl"
        if not (folder / "verdicts.jsonl").is_file():
            failures.append(f"I-3 {rel}: missing")
            continue
        try:
            recorded = _object_rows(folder / "verdicts.jsonl")
            rule = _record_rule(folder)
        except (UnicodeDecodeError, ValueError):
            failures.append(f"I-3 {rel}: not JSON lines of objects")
            continue
        rules = sorted({str(r.get("rule")) for r in recorded})
        if rules and rules != [rule]:
            failures.append(f"I-3 {rel}: rows record {', '.join(rules)}, this record's rule is {rule}")
        try:
            fresh = {r["id"]: r for r in V.load_run(folder, rule)}
        except Exception as exc:
            failures.append(f"I-3 {rel}: the passes can't be read ({type(exc).__name__}: {exc})")
            continue
        failures += _register_agrees(folder, f"{d.name}/runs/{folder.name}/register.jsonl", fresh)
        theirs = {}
        for r in recorded:
            if r.get("id") in theirs:
                failures.append(f"I-3 {rel}: {r.get('id')} listed twice")
            theirs[r.get("id")] = r
        for cid in sorted(set(fresh) | set(theirs), key=lambda c: (_id_number(c), str(c))):
            if cid not in theirs:
                failures.append(f"I-3 {rel}: {cid} has no row")
            elif cid not in fresh:
                failures.append(f"I-3 {rel}: {cid} has a row but no claim")
            elif theirs[cid].get("verdict") != fresh[cid]["verdict"]:
                failures.append(f"I-3 {rel}: {cid} records {theirs[cid].get('verdict')}, the passes give {fresh[cid]['verdict']}")
            elif (fields := sorted(k for k in set(theirs[cid]) | set(fresh[cid])
                                   if k != "rule" and theirs[cid].get(k) != fresh[cid].get(k))):  # a wrong rule is said once, above
                failures.append(f"I-3 {rel}: {cid} records " + ", ".join(
                    f"{k}={theirs[cid].get(k)!r} where the passes give {fresh[cid].get(k)!r}" for k in fields))
    return failures


def _register_agrees(folder, rel, fresh):
    """register.jsonl holds exactly the non-withdrawn claims, each with the verdict word and the low-confidence mark
    the verdict rule gives."""
    if not (folder / "register.jsonl").is_file():
        return [f"I-3 {rel}: missing"]
    try:
        rows = _object_rows(folder / "register.jsonl")
    except (UnicodeDecodeError, ValueError):
        return [f"I-3 {rel}: not JSON lines of objects"]
    failures, register = [], {}
    for r in rows:
        if r.get("id") in register:
            failures.append(f"I-3 {rel}: {r.get('id')} listed twice")
        register[r.get("id")] = r
    expected = {cid: v for cid, v in fresh.items() if not v["withdrawn"]}
    for cid in sorted(set(expected) | set(register), key=lambda c: (_id_number(c), str(c))):
        if cid not in register:
            failures.append(f"I-3 {rel}: {cid} missing")
        elif cid not in expected:
            failures.append(f"I-3 {rel}: {cid} has no published verdict")
        elif register[cid].get("verdict") != REGISTER_WORD.get(expected[cid]["verdict"]):
            failures.append(f"I-3 {rel}: {cid} reads {register[cid].get('verdict')}, verdicts.jsonl reads {expected[cid]['verdict']}")
        elif (register[cid].get("confidence") == "low") != bool(expected[cid]["low_confidence"]):
            failures.append(f"I-3 {rel}: {cid} low confidence differs from verdicts.jsonl")
    return failures


def id_reuse(root):
    """I-6 (VR-06): per domain, runs in fetched_at order; every id is carried from the run's previous_run (an earlier run
    of the domain) or is above every id of every earlier run. Ids compare as numbers."""
    failures = []
    for d in _domain_dirs(root):
        if d.is_symlink():
            continue
        runs = []
        for folder in _run_folders(d):
            rel = f"{d.name}/runs/{folder.name}"
            try:
                meta = json.loads((folder / "run.json").read_text(encoding="utf-8"))
                claim_ids = [row["id"] for row in _object_rows(folder / "claims.jsonl")]
            except Exception as exc:
                failures.append(f"I-6 {rel}: run.json or claims.jsonl unreadable ({type(exc).__name__})")
                continue
            try:
                when = datetime.datetime.fromisoformat(meta.get("fetched_at"))
            except (TypeError, ValueError):
                when = None
            if when is None or when.tzinfo is None:
                failures.append(f"I-6 {rel}: fetched_at is missing or has no zone")
                continue
            # The published baseline; an imported record predates the field and names its baseline as previous_run.
            baseline = meta["published_baseline"] if "published_baseline" in meta else meta.get("previous_run")
            fresh_list = meta.get("previous_run") in (None, "none")
            runs.append((when.astimezone(datetime.timezone.utc), folder.name, baseline, claim_ids, fresh_list))
        seen, high, before = {}, 0, None
        for _when, name, baseline, claim_ids, fresh_list in sorted(runs, key=lambda r: (r[0], r[1])):
            rel = f"{d.name}/runs/{name}"
            carried = set() if fresh_list else seen.get(before, set())
            if baseline != before:
                failures.append(f"I-6 {rel}: baseline {baseline} is not the run before it ({before or 'none'})")
            before = name
            for cid, n in sorted(collections.Counter(claim_ids).items(), key=lambda kv: (_id_number(kv[0]), str(kv[0]))):
                if _id_number(cid) < 0:
                    failures.append(f"I-6 {rel}: {cid!r} is not a claim id")
                elif n > 1:
                    failures.append(f"I-6 {rel}: {cid} listed {n} times")
                if 0 <= _id_number(cid) <= high and cid not in carried:
                    failures.append(f"I-6 {rel}: {cid} is neither carried from its previous_run nor above the highest earlier id")
            seen[name] = set(claim_ids)
            high = max([high] + [_id_number(c) for c in claim_ids])
    return failures


def _exclusions_expected(root):
    expected = {}
    for domain, _meta, run in domains(root):
        data = json.loads((run / "run.json").read_text(encoding="utf-8")) if (run / "run.json").is_file() else {}
        expected[domain] = data.get("exclusions", [])
    return expected


def toolkit_pin(root):
    """I-9: the toolkit build.py loads (tools/toolkit beside it) equals its MANIFEST, TOOLKIT_VERSION names that
    MANIFEST, and config/exclusions.json equals each domain's current run's exclusions."""
    failures, manifest, version = [], KIT / "MANIFEST", KIT / "TOOLKIT_VERSION"
    if not manifest.is_file():
        failures.append("I-9 tools/toolkit/MANIFEST: missing")
    else:
        data = manifest.read_bytes()
        listed = {}
        for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            sha, sep, name = line.partition("  ")
            if not line.strip():
                continue
            if not sep or not HEX64.match(sha) or not name:
                failures.append(f"I-9 tools/toolkit/MANIFEST:{n}: not a hash and a path")
            elif name in listed:
                failures.append(f"I-9 tools/toolkit/{name}: listed twice in MANIFEST")
            else:
                listed[name] = sha
        present = {p.relative_to(KIT).as_posix(): p for p in sorted(KIT.rglob("*"))
                   if p.is_file() and "__pycache__" not in p.relative_to(KIT).parts and p not in (manifest, version)}
        for name in sorted(set(listed) | set(present)):
            if name not in present:
                failures.append(f"I-9 tools/toolkit/{name}: listed in MANIFEST but missing")
            elif name not in listed:
                failures.append(f"I-9 tools/toolkit/{name}: not listed in MANIFEST")
            elif hashlib.sha256(present[name].read_bytes()).hexdigest() != listed[name]:
                failures.append(f"I-9 tools/toolkit/{name}: does not match MANIFEST")
        words = version.read_text(encoding="utf-8").split() if version.is_file() else []
        if not version.is_file():
            failures.append("I-9 tools/toolkit/TOOLKIT_VERSION: missing")
        elif len(words) != 2 or words[1] != hashlib.sha256(data).hexdigest():
            failures.append("I-9 tools/toolkit/TOOLKIT_VERSION: does not name this MANIFEST")
        elif words[0].endswith("+local"):
            failures.append(f"I-9 tools/toolkit/TOOLKIT_VERSION: {words[0]} vendored from an uncommitted argus-claims tree")
        elif not COMMIT.match(words[0]):
            failures.append(f"I-9 tools/toolkit/TOOLKIT_VERSION: {words[0]} is not a commit id")
    config = pathlib.Path(root) / "config" / "exclusions.json"
    if not config.is_file():
        return failures + ["I-9 config/exclusions.json: missing"]
    try:
        rules = json.loads(config.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, ValueError):
        return failures + ["I-9 config/exclusions.json: not JSON"]
    if not isinstance(rules, dict):
        return failures + ["I-9 config/exclusions.json: not an object of domains"]
    expected = _exclusions_expected(root)
    for domain in sorted(set(expected) | set(rules)):
        if domain not in rules:
            failures.append(f"I-9 config/exclusions.json: {domain} missing")
        elif domain not in expected:
            failures.append(f"I-9 config/exclusions.json: {domain} is not a domain here")
        elif rules[domain] != expected[domain]:
            failures.append(f"I-9 config/exclusions.json: {domain} differs from its current run's run.json")
    return failures


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True, text=True).stdout


def _z(text):
    return [part for part in text.split("\0") if part]


def _run_folder_of(path):
    parts = path.split("/")
    return "/".join(parts[:3]) if len(parts) >= 4 and DOMAIN.match(parts[0]) and parts[1] == "runs" else None


def _index_parts(text):
    """index.md as (front-matter lines other than current_run, body lines); the whole text when it has no front matter."""
    lines = text.splitlines()
    fences = [n for n, line in enumerate(lines) if line.strip() == "---"]
    if len(fences) < 2 or fences[0] != 0:
        return lines, None
    return [l for l in lines[1:fences[1]] if not l.strip().startswith("current_run:")], lines[fences[1] + 1:]


def immutability(root, base, publication=False):
    """I-5 (VR-08): against the git base, with files as git sees them (tracked, plus untracked files it doesn't
    ignore), no file of a run folder that exists at the base is changed, deleted or joined by a new one. With
    `publication` (a claims/* PR), the change adds exactly one run folder and nothing else but its domain's index.md
    (current_run only), changelog.md (append), its config/exclusions.json entry and new prompts named by their hash."""
    root = pathlib.Path(root)
    try:
        if pathlib.Path(_git(root, "rev-parse", "--show-toplevel").strip()).resolve() != root.resolve():
            return [f"I-5 {root}: not the top folder of its git repository"]
        before = set(_z(_git(root, "ls-tree", "-r", "-z", "--name-only", base)))
        diff = _z(_git(root, "diff", "--no-renames", "--name-status", "-z", base, "--"))
        untracked = set(_z(_git(root, "ls-files", "-z", "--others", "--exclude-standard")))
    except subprocess.CalledProcessError:
        return [f"I-5 base {base}: not a git commit here"]
    status = dict(zip(diff[1::2], (s[0] for s in diff[0::2])))
    status.update({p: "A" for p in untracked})
    old_folders = {_run_folder_of(p) for p in before} - {None}
    said = {"D": "deleted since the base", "A": "added to a published run folder"}
    failures = [f"I-5 {p}: {said.get(s, 'changed since the base')}" for p, s in sorted(status.items())
                if _run_folder_of(p) in old_folders]
    return failures + (_publication(root, base, before, status, old_folders) if publication else [])


def _publication(root, base, before, status, old_folders):
    present = {p for p, s in status.items() if s != "D"} | (before - set(status))
    new_folders = sorted({_run_folder_of(p) for p in present} - old_folders - {None})
    failures = [] if len(new_folders) == 1 else [f"I-5 publication: adds {len(new_folders)} run folders, a publication adds one"]
    new = new_folders[0] if len(new_folders) == 1 else None
    domain = new.split("/")[0] if new else None  # None: no single new run, so any domain's files get the content rules

    def old_text(p):
        return _git(root, "show", f"{base}:{p}")

    for p, s in sorted(status.items()):
        parts = p.split("/")
        own = len(parts) == 2 and bool(DOMAIN.match(parts[0])) and domain in (None, parts[0]) and s != "D"
        prompt = PROMPT.match(p)
        if _run_folder_of(p) is not None:
            continue  # inside the new folder (counted above) or an old one (reported above)
        if prompt and s == "A":
            if hashlib.sha256((root / p).read_bytes()).hexdigest() != prompt.group(1):
                failures.append(f"I-5 {p}: not named by the sha256 of its text")
        elif own and parts[1] == "index.md":
            if p in before and _index_parts(old_text(p)) != _index_parts((root / p).read_text(encoding="utf-8")):
                failures.append(f"I-5 {p}: changes more than current_run")
        elif own and parts[1] == "changelog.md":
            old = old_text(p) if p in before else ""
            if not (old == "" or old.endswith("\n")) or not (root / p).read_text(encoding="utf-8").startswith(old):
                failures.append(f"I-5 {p}: not an append")
        elif p == "config/exclusions.json" and s != "D":
            old = json.loads(old_text(p)) if p in before else {}
            fresh = json.loads((root / p).read_text(encoding="utf-8"))
            if {k: v for k, v in old.items() if k != domain} != {k: v for k, v in fresh.items() if k != domain}:
                failures.append(f"I-5 {p}: changes another domain's entry")
        else:
            failures.append(f"I-5 {p}: not part of a publication")
    if new and (root / domain / "index.md").is_file():
        current = front_matter(root / domain / "index.md")["current_run"]
        if current != new.split("/")[2]:
            failures.append(f"I-5 {domain}/index.md: current_run is {current}, the new run is {new.split('/')[2]}")
    return failures


def secrets(root, out, log):
    """I-8 (VR-11): no marker in the tree (all but the root .git), the build output or the build log. Names the file,
    never the text."""
    failures = []
    for base, label, skip in [(pathlib.Path(root), "", (".git",))] + ([(out, "dist/", ())] if out else []):
        for path in _files(base, skip):
            if _has_marker(path.read_bytes()):
                failures.append(f"I-8 {label}{path.relative_to(base).as_posix()}: carries a secret marker")
    for n, line in enumerate(log or [], 1):
        if _has_marker(line):
            failures.append(f"I-8 build log line {n}: carries a secret marker")
    return failures


def check(root, base=None, publication=False):
    """The invariants built so far, as one line per failure (empty = pass). A failed build is reported and the checks
    that need no build (I-3, I-4, I-5, I-6, I-8 on the tree, I-9) still run; a check that crashes is reported, not
    raised. I-5 needs a git base."""
    root = pathlib.Path(root)
    failures = []
    with tempfile.TemporaryDirectory() as t:
        a, b = pathlib.Path(t) / "a", pathlib.Path(t) / "b"
        try:
            log = build(root, a) + build(root, b)
        except Exception as exc:  # reported, not raised: the tree checks below still run
            failures.append(f"build {type(exc).__name__}: {exc}")
            log, a = None, None
        steps = [("I-3", lambda: verdict_recompute(root)), ("I-4", lambda: manifests(root)),
                 ("I-6", lambda: id_reuse(root)), ("I-8", lambda: secrets(root, a, log)), ("I-9", lambda: toolkit_pin(root))]
        if base is not None:
            steps.append(("I-5", lambda: immutability(root, base, publication)))
        if a is not None:
            steps = [("I-1", lambda: determinism(a, b)), ("I-2", lambda: parity(root, a)),
                     ("I-7", lambda: links(a, cited_urls(root)))] + steps
        for name, step in steps:
            try:
                failures += step()
            except Exception as exc:
                failures.append(f"{name} could not run: {type(exc).__name__}: {exc}")
    return [_withheld(f) for f in failures]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(TOOLS.parent))
    ap.add_argument("--out", help="default: <root>/dist")
    ap.add_argument("--check", action="store_true", help="build twice into temporary folders and run the invariants")
    ap.add_argument("--base", help="with --check: the git ref a PR is compared against (I-5)")
    ap.add_argument("--publication", action="store_true", help="with --base: the change is a claims/* publication")
    a = ap.parse_args(argv)
    if a.base and not a.check or a.publication and not a.base:
        ap.error("--base needs --check, and --publication needs --base")
    if a.check:
        if a.out:
            ap.error("--check builds into temporary folders; --out is not used")
        failures = check(a.root, a.base, a.publication)
        for line in failures:
            print(line)
        print(f"check: {len(failures)} failure(s)")
        return 1 if failures else 0
    try:
        log = build(a.root, a.out or pathlib.Path(a.root) / "dist")
    except BuildError as exc:
        print(_withheld(f"build: {exc}"), file=sys.stderr)
        return 1
    if any(_has_marker(line) for line in log):
        print("build: the build log carries a secret marker (not printed); the build is refused", file=sys.stderr)
        return 1
    for line in log:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
