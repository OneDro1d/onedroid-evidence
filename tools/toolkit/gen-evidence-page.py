#!/usr/bin/env python3
"""Generate an evidence page for onedroid.ai/evidence/<domain> from an audit run directory.

    python3 -I gen-evidence-page.py <run_dir> <publisher> <domain> <checked YYYY-MM-DD> <out.html> [--self] [--split-low-confidence] [--changelog-file FILE] [--changelog-extra TEXT] [--certificate-file FILE] [--fragment OUT.html]

--self: the publisher audits itself (texts change, structure and ids do not). --changelog-extra: a sentence appended to the
change log. With --split-low-confidence, a CONTRADICTED claim whose disprove note has the word "low" (word boundary, any
case) together with "confidence" is shown in its own "low confidence" section; without the flag every contradicted claim is
in one table (the Kilkenny pages). A judge.json entry {"verdict": "WITHDRAWN", "note": "..."} drops the claim from the page and counts.

<run_dir> holds claims.jsonl, prove.jsonl, disprove.jsonl and claims.md (the lister's source table:
| source URL | local file | HTTP | bytes | sha256 |), plus an optional judge.json with the reviewer's hand rulings.
The page uses the landing site's scaffold (header, nav, footer as on about.html) and the register's third-party record
format from ideas/claims-register-drafts-2026-10-27/claims-md-spec.md. Verdict words are the only three the hard stops
allow. Nothing on the page says true or false.

Page order (Michal, 27 Oct 2026 21:0xZ: "the why, the explanation go first, then the claims + evidence, the sources go
last; easy to read by AI agents, not pretty"):
  1. what this page is, the three verdicts and their counts, the rules, the limits, the right of reply, the change log
  2. the claims with their evidence: contradicted, evidenced, no evidence published; every row has id="C-nnn"
  3. the sources as fetched, with HTTP status and sha256
No scroll-reveal animation: the site's .reveal class hides a section until 12% of it is on screen, which a table of 67
rows never reaches, so the section stayed invisible (the "huge empty gap" he saw on 27 Oct). Plain sections only.
The Markdown twin is produced by the landing repo's tools/gen-md-twins.py from this HTML; add the page to PAGES in
tools/gen-llms-full.py and to the middleware PAGES set.
"""
import html
import json
import argparse
import pathlib
import re
import sys

VERDICTS = {
    "EVIDENCED": "an artefact on the company's own surfaces would be false if the claim were",
    "CONTRADICTED": "the company's own surfaces disagree with the claim; both sides are referenced",
    "NO EVIDENCE PUBLISHED": "the claim is stated; nothing beyond the statement backs it in the sources checked",
}
PRIVATE_WORD = "EVIDENCE PRIVATE"  # claims.md 0.2 (Michal, D18, 1 Nov 2026): never "evidenced", shown only on pages that use it
PRIVATE_MEANING = ("the holder showed us an artefact that would be false if the claim were, and its sha256 matched; it is not published, "
                   "so a reader cannot check it from this page and should ask the holder")


def load(path):
    rows = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line)
            rows[o["id"]] = o
    return rows


JUDGE = {}   # optional <run_dir>/judge.json: {"C-042": {"verdict": "...", "note": "..."}}, the judge's hand rulings
PRIVATE = {}   # optional <run_dir>/private-evidence.json: {"C-042": {"holder", "sha256", "shown", "note"}}, artefacts shown to us


def verdict(cid, prove, disprove):
    if cid in JUDGE and JUDGE[cid].get("verdict") in VERDICTS:
        return JUDGE[cid]["verdict"]
    if disprove.get(cid, {}).get("contradiction") == "yes":
        return "CONTRADICTED"
    if prove.get(cid, {}).get("evidence") == "artefact":
        return "EVIDENCED"
    return PRIVATE_WORD if cid in PRIVATE else "NO EVIDENCE PUBLISHED"


def e(s):
    return html.escape(str(s), quote=True)


LOW_WORD = re.compile(r"\blow\b", re.I)
CONFIDENCE_WORD = re.compile(r"confiden", re.I)


def is_low(cid, prove, disprove):
    """CONTRADICTED and the disprove note has the word "low" (word boundary, so not "below" or "allow") together with
    "confidence". Narrower than gen-rerun-report.py's substring rule, which matched "below"; same result on the 27 Oct runs."""
    note = str(disprove.get(cid, {}).get("note", ""))
    return (verdict(cid, prove, disprove) == "CONTRADICTED"
            and bool(LOW_WORD.search(note)) and bool(CONFIDENCE_WORD.search(note)))


def no_evidence_phrase(counts):
    """'<n> with no evidence published', and the evidence-private count when a page uses that word."""
    text = f"{counts['NO EVIDENCE PUBLISHED']} with no evidence published"
    return f"{text}, {counts[PRIVATE_WORD]} with evidence private" if PRIVATE_WORD in counts else text


def contra_phrase(n, low):
    """'<n> contradicted' or, when some are low confidence, '<n> contradicted (<low> of them low confidence)'."""
    return f"{n} contradicted" if not low else f"{n} contradicted ({low} of them low confidence)"


def source_rows(run):
    """The lister's source table: rows whose first cell is the URL, or whose first cell is a row number followed by the
    URL (the 28 Oct 2026 lister numbered its rows). Returned as [url, file, http, bytes, sha256]; a row whose sha256
    cell is not 64 characters is skipped."""
    out = []
    for line in (run / "claims.md").read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0].isdigit() and len(cells) >= 2 and cells[1].startswith("http"):
            cells = cells[1:]
        if cells and cells[0].startswith("http") and len(cells) >= 5 and len(cells[4]) == 64:
            out.append(cells[:5])
    return out


def head(publisher, domain, checked, counts, total, low=0):
    title = f"{publisher}: its public claims and the evidence behind them"
    desc = (f"Every checkable claim {domain} makes on its own public pages, where it is made, and what backs it: "
            f"{counts['EVIDENCED']} evidenced, {contra_phrase(counts['CONTRADICTED'], low)}, "
            f"{no_evidence_phrase(counts)}, of {total}. Checked {checked}. "
            "Nothing here says true or false.")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{e(title)} — OneDroid evidence</title>
  <meta name="description" content="{e(desc)}">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <link rel="canonical" href="https://onedroid.ai/evidence/{e(domain)}">
  <link rel="alternate" type="text/markdown" href="https://onedroid.ai/evidence/{e(domain)}.md">

  <meta property="og:type" content="article">
  <meta property="og:title" content="{e(title)}">
  <meta property="og:description" content="{e(desc)}">
  <meta property="og:url" content="https://onedroid.ai/evidence/{e(domain)}">
  <meta property="og:image" content="https://onedroid.ai/assets/og-wordmark.png">
  <meta name="twitter:card" content="summary_large_image">

  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/styles.css">

  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "Dataset",
    "name": "{e(title)}",
    "url": "https://onedroid.ai/evidence/{e(domain)}",
    "dateModified": "{e(checked)}",
    "description": "{e(desc)}",
    "about": {{"@type": "Organization", "name": "{e(publisher)}", "url": "https://{e(domain)}"}},
    "creator": {{"@type": "Organization", "name": "OneDroid", "url": "https://onedroid.ai"}},
    "license": "https://creativecommons.org/licenses/by/4.0/"
  }}
  </script>
</head>
<body>

<header class="site-header">
  <div class="container header-inner">
    <a class="wordmark" href="/" aria-label="OneDroid home">OneDro<span class="wm-1d">1d</span></a>
    <nav class="site-nav" aria-label="Main">
      <a href="/argus">OneDroid Argus</a>
      <a href="/synapse">Synapse</a>
      <a href="/engram">Engram</a>
      <a href="https://docs.onedroid.ai">Docs</a>
      <a href="/enterprise">Enterprise</a>
      <a href="/pricing">Pricing</a>
    </nav>
    <a class="header-gh" href="https://github.com/OneDro1d"
       aria-label="OneDroid on GitHub — open source">
      <svg viewBox="0 0 16 16" width="18" height="18" fill="currentColor" aria-hidden="true" focusable="false"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.012 8.012 0 0 0 16 8c0-4.42-3.58-8-8-8z"></path></svg>
    </a>
    <a class="btn btn-secondary header-cta" href="/argus#install">Get started</a>
  </div>
</header>

<main>
"""


FOOTER = """
</main>

<footer class="site-footer">
  <div class="container footer-inner">
    <div>
      <span class="wordmark wordmark-sm">OneDro<span class="wm-1d">1d</span></span>
      <p class="footer-line">OneDroid Argus — built by <a href="https://www.providentiaworldwide.com/">Providentia Worldwide</a>.</p>
      <p class="footer-line muted">OneDroid (onedroid.ai) builds AI agent infrastructure. Unrelated to Android or the OneDroid Android projects.</p>
    </div>
    <nav class="footer-nav" aria-label="Footer">
      <a href="/argus">OneDroid Argus</a>
      <a href="/synapse">OneDroid Synapse</a>
      <a href="/engram">OneDroid Engram</a>
      <a href="/evidence/onedroid.ai">Our claims, with evidence</a>
      <a href="/evidence">Evidence pages</a>
      <a href="https://docs.onedroid.ai">Docs</a>
      <a href="/case-studies">Case studies</a>
      <a href="/pricing">Pricing</a>
      <a href="/security">Security</a>
      <a href="/about">About</a>
      <a href="/contact">Contact</a>
      <a href="/privacy">Privacy</a>
      <a href="/terms">Terms</a>
      <a href="/llms.txt">llms.txt</a>
      <a href="https://github.com/OneDro1d">GitHub</a>
      <a href="mailto:michal@onedroid.ai">michal@onedroid.ai</a>
    </nav>
  </div>
</footer>
</body>
</html>
"""


def refs_html(refs):
    return "<br>".join(e(r) for r in refs[:3]) if refs else ""


def claims_and_sources_html(claims, prove, disprove, low_ids, srcs, checked, sources_note=""):
    """The claims sections (contradicted, low confidence, evidenced, no evidence) and the sources section, as one string."""
    L = []
    for section, key, anchor in (("Contradicted", "CONTRADICTED", "contradicted"),
                                 ("Contradicted, low confidence", "CONTRADICTED", "contradicted-low-confidence"),
                                 ("Evidenced", "EVIDENCED", "evidenced"),
                                 ("No evidence published", "NO EVIDENCE PUBLISHED", "no-evidence-published"),
                                 ("Evidence private", PRIVATE_WORD, "evidence-private")):
        rows = [cid for cid in claims if verdict(cid, prove, disprove) == key]
        if key == "CONTRADICTED":
            rows = [cid for cid in rows if (cid in low_ids) == (anchor == "contradicted-low-confidence")]
        if not rows:
            continue
        intro = ""
        if anchor == "contradicted-low-confidence":
            intro = ("\n      <p>The disprove pass itself said a charitable reading reconciles each of these: a dated historical "
                     "entry, a paraphrase, a feature documented for the hosted service but not yet in the public code snapshot. "
                     "They are listed because the two surfaces do disagree as written.</p>")
        L.append(f"""
  <section class="section" id="{anchor}">
    <div class="container">
      <h2>{section} ({len(rows)})</h2>{intro}
      <div class="cs-table-wrap"><table class="cs-table">
        <thead><tr><th>Id</th><th>Claim, as made</th><th>Made at</th><th>{'Both sides' if key == 'CONTRADICTED' else ('Artefact' if key == 'EVIDENCED' else ('What we were shown' if key == PRIVATE_WORD else 'What would close it'))}</th></tr></thead>
        <tbody>""")
        for cid in rows:
            c = claims[cid]
            made = "<br>".join(f"<a href=\"{e(s['url'])}\">{e(s['url'].replace('https://', ''))}</a> ({e(s.get('locator', ''))})" for s in c["sources"][:3])
            if key == "CONTRADICTED":
                d = disprove[cid]
                cell = f"{e(d.get('note', ''))}<br>{refs_html(d.get('refs', []))}"
            elif key == "EVIDENCED":
                p = prove[cid]
                cell = f"{refs_html(p.get('refs', []))}<br>{e(p.get('note', ''))}"
            elif key == PRIVATE_WORD:
                r = PRIVATE[cid]
                cell = (f"Held by {e(r['holder'])}, shown to us on {e(r['shown'])}, shared on request.<br>sha256 <code>{e(r['sha256'])}</code>"
                        + (f"<br>{e(r['note'])}" if r.get("note") else ""))
            else:
                cell = e(prove.get(cid, {}).get("note", ""))
            if cid in JUDGE and JUDGE[cid].get("note"):
                cell += f"<br><em>Reviewer's note: {e(JUDGE[cid]['note'])}</em>"
            L.append(f"<tr id=\"{e(cid)}\"><td>{e(cid)}</td><td>{e(c['claim'])}</td><td>{made}</td><td>{cell}</td></tr>")
        L.append("""</tbody></table></div>
    </div>
  </section>
""")

    # 3. The sources, last.
    L.append(f"""
  <section class="section" id="sources">
    <div class="container">
      <h2>Sources as fetched</h2>
      <p>Every verdict above points into one of these files. To check one, fetch the URL with a browser user-agent and run
        sha256sum on the bytes; a different fingerprint means the page changed after {e(checked)}.{sources_note}</p>
      <div class="cs-table-wrap"><table class="cs-table">
        <thead><tr><th>Source</th><th>HTTP</th><th>sha256 as fetched</th></tr></thead>
        <tbody>""")
    for cells in srcs:
        L.append(f"<tr><td><a href=\"{e(cells[0])}\">{e(cells[0])}</a></td><td>{e(cells[2])}</td><td><code>{e(cells[4])}</code></td></tr>")
    L.append("""</tbody></table></div>
    </div>
  </section>
""")
    return "".join(L)


FRAGMENT_START = "<!-- claims-register:start generated by tools/claims-audit/gen-evidence-page.py, do not edit by hand -->"
FRAGMENT_END = "<!-- claims-register:end -->"


def fragment_html(claims, prove, disprove, low_ids, srcs, checked, domain, counts, total, contra, sources_note=""):
    """The claims register as an embeddable block for another page (no head, header or footer)."""
    return f"""{FRAGMENT_START}
<section class="section claims-embed" id="claims">
  <div class="container">
    <h2>Every checkable claim this site makes, and what backs it</h2>
    <p>{total} claims as of {e(checked)}: {counts['EVIDENCED']} evidenced, {contra}, {no_evidence_phrase(counts)}. The same {'' if PRIVATE_WORD in counts else 'three '}verdicts, rules and limits as on <a href="/evidence/{e(domain)}">the full page</a>, which also carries the change log and how to correct a line. Nothing here says a claim is true or false; every reference points into a source whose sha256 as fetched is listed at the end.</p>
  </div>
</section>
{claims_and_sources_html(claims, prove, disprove, low_ids, srcs, checked, sources_note)}
{FRAGMENT_END}
"""


def certificate_html(url, note):
    """A 'Certificate' paragraph for the how-to-read section: the note (escaped) and the certificate URL as a link.
    Nothing when no URL is given."""
    if not url:
        return ""
    text = (e(note) + " ") if note else ""
    return (f"""<h3>Certificate</h3>
      <p>{text}<a href="{e(url)}">{e(url)}</a></p>
      """)


CONNECTOR_NOTE = (" Social profiles are the exception: they were read through our connector, and those bytes include counts and signed "
                  "media links that change, so a reader cannot re-fetch the same bytes; compare a post's text at its own URL instead. "
                  "A social profile here is a dated sample of recent posts, not the whole account.")

CONNECTOR_SOURCES_NOTE = (" Social profiles are the exception: the fingerprint is of exactly what the connector returned; those bytes include "
                          "counts and signed media links that change, so a second read will not match, and that alone does not mean a post changed.")


def read_changelog(path):
    """The page's change log as data: one entry per line, oldest first, whole text as published (not escaped). Blank lines are skipped."""
    return [line.strip() for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def build(run, publisher, domain, checked, self_mode=False, changelog_extra=None, detail=False, split_low=False, fragment_out=None,
          certificate_url=None, certificate_note=None, changelog_entries=None):
    claims = load(run / "claims.jsonl")
    prove = load(run / "prove.jsonl")
    disprove = load(run / "disprove.jsonl")
    JUDGE.clear()
    if (run / "judge.json").exists():
        JUDGE.update(json.loads((run / "judge.json").read_text(encoding="utf-8")))
    PRIVATE.clear()
    if (run / "private-evidence.json").exists():
        PRIVATE.update(json.loads((run / "private-evidence.json").read_text(encoding="utf-8")))
    withdrawn = [(cid, JUDGE[cid].get("note", "")) for cid in claims
                 if cid in JUDGE and JUDGE[cid].get("verdict") == "WITHDRAWN"]
    claims = {cid: c for cid, c in claims.items() if not (cid in JUDGE and JUDGE[cid].get("verdict") == "WITHDRAWN")}
    counts = {k: 0 for k in VERDICTS}
    if PRIVATE:
        counts[PRIVATE_WORD] = 0
    for cid in claims:
        counts[verdict(cid, prove, disprove)] += 1
    low_ids = [cid for cid in claims if is_low(cid, prove, disprove)] if split_low else []
    low = len(low_ids)
    contra = contra_phrase(counts['CONTRADICTED'], low)
    total = len(claims)
    srcs = source_rows(run)
    run_json = json.loads((run / "run.json").read_text(encoding="utf-8")) if (run / "run.json").exists() else {}
    connector_note = CONNECTOR_NOTE if run_json.get("connector_hosts") else ""
    sources_note = CONNECTOR_SOURCES_NOTE if connector_note else ""
    verdicts_sentence = ("These are the only three verdicts, and evidence private is the one further word: it is not evidenced." if PRIVATE_WORD in counts
                         else "These are the only three verdicts.")
    L = [head(publisher, domain, checked, counts, total, low)]
    if self_mode:
        eyebrow = f"Evidence page · {e(domain)} · checked {e(checked)} · on ourselves"
        hero = f"""This page lists the checkable claims <a href="https://{e(domain)}">{e(domain)}</a> makes on its own public pages,
        in its docs and in its public repository, where each claim is made, and what {e(publisher)} has published that backs it.
        {e(publisher)} checked itself on {e(checked)}, with the same method and the same three verdicts it applies to other
        companies' pages, from its own public sources only: {total} claims, {counts['EVIDENCED']} evidenced,
        {contra}, {no_evidence_phrase(counts)}.
        Nothing on this page says a claim is true or false. Every reference points into a source whose sha256 as fetched is
        listed at the end of the page, so anyone can fetch the same bytes and compare.{connector_note} The same page as Markdown:
        <a href="/evidence/{e(domain)}.md">/evidence/{e(domain)}.md</a>."""
        limits_tail = (f"The reviewers are AI agents run by {e(publisher)}, checked by hand on a sample. {e(publisher)} checked "
                       "itself, so this page is a self-report made with a disclosed method, not an independent audit; the "
                       "sources as fetched are fingerprinted below so anyone can repeat it.")
        reply = f"""<h3>Corrections</h3>
      <p>If a line on this page is wrong, write to <a href="mailto:michal@onedroid.ai">michal@onedroid.ai</a> naming the claim id.
        A wrong quote, URL or fingerprint is corrected and listed in the change log. When a contradicted claim is fixed on the
        site, it is checked again from the new sources, with a new date and new fingerprints, and the verdict changes when the
        evidence supports it; the date of the fix is recorded in the change log.</p>"""
    else:
        eyebrow = f"Evidence page · {e(domain)} · checked {e(checked)}"
        hero = f"""This page lists the checkable claims <a href="https://{e(domain)}">{e(domain)}</a> makes on its own public pages,
        where each claim is made, and what the company itself has published that backs it. It was checked on {e(checked)}
        by OneDroid, a third party, from the company's own public sources only: {total} claims, {counts['EVIDENCED']} evidenced,
        {contra}, {no_evidence_phrase(counts)}.
        Nothing on this page says a claim is true or false. Every reference points into a source whose sha256 as fetched is
        listed at the end of the page, so anyone can fetch the same bytes and compare.{connector_note} The same page as Markdown:
        <a href="/evidence/{e(domain)}.md">/evidence/{e(domain)}.md</a>."""
        limits_tail = ("The reviewers are\n        AI agents run by OneDroid, checked by hand on a sample; "
                       "OneDroid is not independent of its own method.")
        reply = f"""<h3>Right of reply</h3>
      <p>If you are {e(publisher)} and a line is wrong, write to <a href="mailto:michal@onedroid.ai">michal@onedroid.ai</a>
        naming the claim id. Your answer is shown beside the verdict, in full and unedited, with its date, and does not replace
        the verdict. If you publish new evidence, the claim is checked again from the new sources, with a new date and new
        fingerprints, and the verdict changes when the evidence supports it. A wrong quote, URL or fingerprint is corrected
        on request and listed in the change log.</p>"""
    changelog = " ".join(e(x) for x in changelog_entries) if changelog_entries else f"{e(checked)}: first run."
    if withdrawn:
        changelog += " Withdrawn by the reviewer before publication: " + ", ".join(f"{e(cid)} ({e(n)})" for cid, n in withdrawn) + "."
    if changelog_extra:
        changelog += " " + e(changelog_extra)

    # 1. What this page is, how to read it, the rules, the limits, the right of reply.
    L.append(f"""
  <section class="page-hero">
    <div class="container">
      <a class="back-link" href="/evidence">Evidence pages</a>
      <p class="eyebrow">{eyebrow}</p>
      <h1>{e(publisher)}: its public claims, <br>and the evidence behind them.</h1>
      <p class="hero-sub">
        {hero}
      </p>
    </div>
  </section>

  <section class="section" id="how-to-read">
    <div class="container">
      <h2>How to read this page</h2>
      <div class="cs-table-wrap"><table class="cs-table">
        <thead><tr><th>Verdict</th><th>Meaning</th><th>Count</th></tr></thead>
        <tbody>""")
    for k, d in {**VERDICTS, **({PRIVATE_WORD: PRIVATE_MEANING} if PRIVATE_WORD in counts else {})}.items():
        cnt = f"{counts[k]} ({low} low confidence)" if (k == "CONTRADICTED" and low) else counts[k]
        L.append(f"<tr><td>{e(k)}</td><td>{e(d)}</td><td>{cnt}</td></tr>")
    L.append(f"""</tbody></table></div>
      <p>{verdicts_sentence} They are statements about the company's own published sources as fetched on
        {e(checked)}, not about the world. A claim with no evidence published may well be true; the page says only that
        the company has not shown it. A contradicted claim may have a reading that reconciles the two sources; where the
        reviewers saw one, the note says so. Each claim has an id (C-001, C-002, ...) that is also its anchor on this page.
        The method and the rules for every page are on the <a href="/evidence">evidence pages index</a>.</p>
      <h3>Limits</h3>
      <p>Same sources only: the reviewers read what the company published and nothing else. They did not test the product,
        interview anyone or use outside records. Every verdict is about the sources as fetched on {e(checked)}; a page can
        change after that. One run is a sample of a moving site: a claim not listed may be right or wrong. {limits_tail}</p>
      {reply}
      {certificate_html(certificate_url, certificate_note)}<h3>Change log</h3>
      <p>{changelog}</p>
    </div>
  </section>
""")

    # 2. The claims and their evidence, 3. the sources, last.
    L.append(claims_and_sources_html(claims, prove, disprove, low_ids, srcs, checked, sources_note))
    L.append(FOOTER)
    if fragment_out is not None:
        fragment_out.append(fragment_html(claims, prove, disprove, low_ids, srcs, checked, domain, counts, total, contra, sources_note))
    if detail:
        return "".join(L), counts, low, [cid for cid, _ in withdrawn]
    return "".join(L), counts


def main():
    ap = argparse.ArgumentParser(description="Generate an evidence page from an audit run directory.")
    for name in ("run_dir", "publisher", "domain", "checked", "out"):
        ap.add_argument(name)
    ap.add_argument("--self", dest="self_mode", action="store_true", help="the publisher audits itself")
    ap.add_argument("--changelog-extra", default=None, help="a sentence appended to the change log paragraph")
    ap.add_argument("--changelog-file", default=None, metavar="FILE",
                    help="the whole change log, one entry per line, in place of the generated first-run sentence")
    ap.add_argument("--fragment", default=None, metavar="OUT.html",
                    help="also write the claims and sources sections alone, between claims-register markers, for embedding")
    ap.add_argument("--split-low-confidence", dest="split_low", action="store_true",
                    help="show contradicted claims whose disprove note says low confidence in their own section")
    ap.add_argument("--certificate-url", default=None, metavar="URL",
                    help="link to a certificate for these pages, shown as a 'Certificate' paragraph in How to read")
    ap.add_argument("--certificate-note", default=None, metavar="TEXT",
                    help="a sentence (HTML-escaped) shown before the certificate link; needs --certificate-url")
    ap.add_argument("--certificate-file", default=None, metavar="FILE",
                    help='JSON {"url": ..., "note": ...}, in place of --certificate-url and --certificate-note')
    a = ap.parse_args()
    if a.certificate_file and (a.certificate_url or a.certificate_note):
        ap.error("--certificate-file replaces --certificate-url and --certificate-note")
    if a.certificate_note and not a.certificate_url:
        ap.error("--certificate-note needs --certificate-url")
    if a.certificate_file:
        cert = json.loads(pathlib.Path(a.certificate_file).read_text(encoding="utf-8"))
        a.certificate_url, a.certificate_note = cert["url"], cert.get("note")
    entries = read_changelog(a.changelog_file) if a.changelog_file else None
    if a.changelog_file and not entries:
        ap.error("--changelog-file is empty")
    frag = [] if a.fragment else None
    page, counts, low, withdrawn = build(pathlib.Path(a.run_dir), a.publisher, a.domain, a.checked,
                                         a.self_mode, a.changelog_extra, detail=True, split_low=a.split_low,
                                         fragment_out=frag, certificate_url=a.certificate_url,
                                         certificate_note=a.certificate_note, changelog_entries=entries)
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.out).write_text(page, encoding="utf-8")
    if a.fragment:
        pathlib.Path(a.fragment).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(a.fragment).write_text(frag[0], encoding="utf-8")
    print(json.dumps({"out": a.out, "counts": counts, "low_confidence": low, "withdrawn": withdrawn}))


if __name__ == "__main__":
    main()
