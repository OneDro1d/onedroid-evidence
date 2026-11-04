"""The gates on a run (02-sa-data-flow §6, D-04). Reads the run, never changes it.

    python3 -I gates.py <run_dir> [--baseline <dir>] [--previous <dir>] [--flip-rate 0.03] [--rules exclusions.json]
                        [--low-rule confidence-field|note-text] [--out gates.json]

The notepad's gate.py answers for the ids, hashes, grades, carried ids and private evidence; those checks are called
here, not copied. Its holdout is not: a service run has no orchestrator to write one (Q-2). Added here:
- G3 references: every reference resolves and its quote is at the cited lines. G3-contradicted is hard: the sides and
  disprove refs of a contradicted row, which also needs a confidence and two different sides: quotes found at different
  places, words on at least one, and a status alone only for a page the claim names that's gone. G3-evidenced is soft:
  the prove refs of
  an evidenced row, which also fails with no quote or when
  every quote is the claim's own sentence. G3-other is soft: every other reference. A ruled row is settled, except a
  ruling to contradicted, which still needs its sides and confidence.
  Imported runs keep free-form references and are not applicable.
- G4 stability: among carried claims whose own lines and check outcomes are unchanged, the share whose grader verdict
  changed. A check row compares what was checked and how it came out, not its hits or fetched hashes: hits carry line
  numbers, and a fetched page's hash moves with any line on it, so on real runs neither is ever unchanged. Rulings and
  private records aren't the grader, so they don't count. With nothing to compare, or no measured flip rate, it reports
  what it has and is not applicable, never a pass.
- G5 lister: rejects as a share of what the model proposed. Carried claims are not proposals.
G6, G7 and G8 need a live run and come with it. A reference is model output: a path has to be written plainly and stay
inside the run, and a quote has to hold words. Bytes that are a saved page count as that page however they are cited, so
exclusions and the restated rule follow them. Each URL body must match the hash it is stored under. Rows of the wrong
shape block the run before any gate reads them, here and in the baseline, and A1 dry-runs the merge, so what the gates
pass merges. Bad input never stops the gate.
outcome: pass; needs-acknowledgement (a soft gate failed); blocked (an assertion or a hard gate failed). Stdlib only.
Nothing here says true or false.
"""
import argparse
import collections
import hashlib
import html
import json
import math
import os
import pathlib
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate as K  # noqa: E402
import locate as L  # noqa: E402
import merge_run as M  # noqa: E402
import verdict as V  # noqa: E402

VERSION = 1
FLIP_MARGIN = 1.5
FLIP_FLOOR = 2
REJECT_LIMIT = 0.02
ROUNDING = 1e-9
CONFIDENCE = ("high", "medium", "low")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
JSON_REF = re.compile(r"^sources/github-repo\.json#(?P<keys>[\w.-]+)$")
LINE_REF = re.compile(r"^(?P<root>sources|repo)/(?P<path>.+)#L(?P<first>\d{1,9})(?:-L?(?P<last>\d{1,9}))?$")
URL_REF = re.compile(r"^(?P<url>https://\S+)#(?P<status>\d{3})$")
BLOCKQUOTE = re.compile(r"(^|\n)[ \t]*>[ \t]?")
LOCATOR = re.compile(r"^sources/(\S+) (L[\d, L-]+?)(?: \(|$)")
LINE_RANGE = re.compile(r"L(\d+)(?:-(\d+))?")
CHECK_FIELDS = ("check", "query", "url", "status")
EVIDENCE_WORDS = {"EVIDENCED", "NO EVIDENCE PUBLISHED"}
BAD_INPUT = (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError, OverflowError)


def _gate(gid, kind, result, numbers=None, failing_ids=(), detail="", **extra):
    return {"id": gid, "kind": kind, "result": result, "numbers": numbers or {}, "failing_ids": list(failing_ids),
            "detail": detail, **extra}


def _quote_forms(quote):
    """What to search for. A quote copied from a file may keep what locate.py drops: entities, blockquote markers. One
    with no words in it is no quote at all."""
    forms = {L.norm_claim(q) for q in (quote, html.unescape(quote), BLOCKQUOTE.sub(r"\1", quote))}
    return {q for q in forms if any(ch.isalnum() for ch in html.unescape(q))}


class Snapshot:
    """A run's saved material, as a reference may reach it."""

    def __init__(self, run_dir, rules=()):
        self.run = pathlib.Path(run_dir)
        self.rules = rules
        self.domain = None
        self._sources = {}
        self._fetches = None
        self._pages = None
        self._responses = {}

    def _path(self, root, rel):
        """The file under <run>/<root>, or None unless the reference names it plainly and stays inside."""
        base = (self.run / root).resolve()
        path = (base / rel).resolve()
        return path if base in path.parents and str(path) == f"{base}/{rel}" else None

    def source(self, rel):
        if rel not in self._sources:
            raw = (self.run / "sources" / rel).read_text(encoding="utf-8", errors="replace")
            self._sources[rel] = L.Source(rel, raw, self.domain, self.rules)
        return self._sources[rel]

    def fetches(self):
        if self._fetches is None:
            cache = V.load_json(self.run / "http-cache.json")
            tools = V.load_json(self.run / "tool-fetches.json") or []
            self._fetches = {**cache, **{f["url"]: f for f in tools}}
        return self._fetches

    def pages(self):
        """{sha256: file} of the saved pages, from sources.sha256. Repo metadata is not a page."""
        if self._pages is None:
            self._pages = {}
            path = self.run / "sources.sha256"
            lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
            for digest, name in (line.split(None, 1) for line in lines if line.strip()):
                if not JSON_REF.match(name.strip().lstrip("*") + "#x"):
                    self._pages[digest] = name.strip().lstrip("*").removeprefix("sources/")
        return self._pages

    def _repo_source(self, rel, path):
        data = path.read_bytes()
        page = self.pages().get(hashlib.sha256(data).hexdigest())
        if page:
            return self.source(page)
        key = ("repo", rel)
        if key not in self._sources:
            self._sources[key] = L.Source(rel, data.decode("utf-8", "replace"), self.domain, self.rules)
        return self._sources[key]

    def _line_source(self, root, rel, path):
        return self.source(rel) if root == "sources" else self._repo_source(rel, path)

    def is_page(self, item):
        """Whether these bytes are a saved page of the publisher, however the reference is written."""
        ref = str(item.get("ref"))
        m = LINE_REF.match(ref)
        if m and m["root"] == "sources":
            return not JSON_REF.match(f"sources/{m['path']}#x")
        if m:
            path = self._path("repo", m["path"])
            return bool(path) and hashlib.sha256(path.read_bytes()).hexdigest() in self.pages()
        m = URL_REF.match(ref)
        return bool(m) and str(self.fetches().get(m["url"], {}).get("sha256")) in self.pages()

    def _located(self, item):
        """The source of a reference's quote and the (start, end) of the quote in it."""
        forms = _quote_forms(item.get("quote") or "")
        m = LINE_REF.match(str(item.get("ref")))
        if m:
            path = self._path(m["root"], m["path"])
            if path is None or not path.is_file():
                return None, []
            src = self._line_source(m["root"], m["path"], path)
            first, last = int(m["first"]), int(m["last"] or m["first"])
            return src, [(s, e) for q in forms for s, e, a, b in src.spans(q) if first <= a and b <= last]
        return self._url_hits(item, forms)  # a side whose quote occurs twice has already failed as quote-not-unique

    def _url_hits(self, item, forms):
        """The fetched body a URL reference points at, and every place its quote occurs there."""
        m = URL_REF.match(str(item.get("ref")))
        digest = str(self.fetches().get(m["url"], {}).get("sha256")) if m else ""
        if not HEX64.match(digest) or not (self.run / "http-bodies" / digest).is_file():
            return None, []
        page = self.pages().get(digest)
        for src in [self.source(page)] if page else self.response(m["url"], digest):
            found = [(s, e) for q in forms for s, e, _a, _b in src.spans(q)]
            if found:
                return src, found
        return None, []

    def unplaced(self, item):
        """A URL reference whose quote occurs more than once: nothing shows which occurrence it means."""
        return len(self._url_hits(item, _quote_forms(item.get("quote") or ""))[1]) > 1

    def places(self, item):
        """{key: [(start, end)]}: where a quote sits in its file, and in its line, so a line copied to another page is the
        same place."""
        src, found = self._located(item)
        out = collections.defaultdict(list)
        for s, e in found:
            line, at = src.line_around(s, e)
            out[id(src)].append((s, e))
            out[line].append((s - at, e - at))
        return out

    def _check_lines(self, m, forms):
        rel = m["path"]
        path = self._path(m["root"], rel)
        if path is None:
            return "bad-form"
        if not path.is_file():
            return "no-such-file"
        src = self._line_source(m["root"], rel, path)
        first, last = int(m["first"]), int(m["last"] or m["first"])
        count = len(src.lines) - (src.lines[-1] == "")  # a file's closing newline starts no line
        if first < 1 or first > last or last > count:
            return "no-such-line"
        if not forms:
            return "no-quote"
        found = (span for q in forms for span in src.locate([q]))
        return None if any(first <= a and b <= last for a, b in found) else "quote-not-at-lines"

    def _check_url(self, m, forms):
        entry = self.fetches().get(m["url"])
        if entry is None:
            return "url-not-fetched"
        if str(entry.get("status")) != m["status"]:
            return "status-differs"
        if not forms:
            return None
        digest = str(entry.get("sha256"))
        body = self.run / "http-bodies" / digest
        if not HEX64.match(digest) or not body.is_file():
            return "body-not-stored"
        data = body.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            return "body-hash-differs"
        page = self.pages().get(digest)
        if page:  # the saved page, so its excluded blocks stay excluded
            return None if any(q in self.source(page).text for q in forms) else "quote-not-in-body"
        texts = [src.text for src in self.response(m["url"], digest, data)]
        return None if any(q in text for q in forms for text in texts) else "quote-not-in-body"

    def response(self, url, digest, data=None):
        """A fetched body that isn't a saved page, read as text and as HTML, with the exclusion rules matched on its name."""
        if digest not in self._responses:
            raw = (data if data is not None else (self.run / "http-bodies" / digest).read_bytes()).decode("utf-8", "replace")
            name = pathlib.PurePosixPath(urllib.parse.urlsplit(url).path).name or "body"
            self._responses[digest] = [L.Source(name, raw, self.domain, self.rules, is_html=parsed) for parsed in (False, True)]
        return self._responses[digest]

    def _check_json(self, m, forms):
        path = self.run / "sources" / "github-repo.json"
        if not path.is_file():
            return "no-such-file"
        value = json.loads(path.read_text(encoding="utf-8"))
        for key in m["keys"].split("."):
            if not isinstance(value, dict) or key not in value:
                return "no-such-key"
            value = value[key]
        if not forms:
            return "no-quote"
        text = L.norm_claim(value if isinstance(value, str) else json.dumps(value))
        return None if any(q in text for q in forms) else "quote-not-in-value"

    def _check(self, ref, forms):
        m = LINE_REF.match(ref)  # first: graders also cite the one-line JSON as sources/github-repo.json#L1
        if m:
            return self._check_lines(m, forms)
        m = JSON_REF.match(ref)
        if m:
            return self._check_json(m, forms)
        m = URL_REF.match(ref)
        return self._check_url(m, forms) if m else "bad-form"

    def check_ref(self, item):
        """None if the reference holds, otherwise the reason. A reference never raises."""
        if not isinstance(item, dict):
            return "not-structured"
        ref, quote = item.get("ref"), item.get("quote")
        if not isinstance(ref, str) or not isinstance(quote, (str, type(None))):
            return "bad-form"
        try:
            return self._check(ref, _quote_forms(quote or ""))
        except BAD_INPUT:
            return "unreadable"


def _quote(item):
    """A reference's quote, normalised, or nothing when it holds no words."""
    q = L.norm_claim(item.get("quote") or "")
    return q if _quote_forms(q) else ""


def restated(claim_text, refs, snap):
    """True when there are quotes and every one is the claim's own sentence. On a saved page, either may sit inside the
    other. Elsewhere (a licence file, a response) a short quote inside the claim is the artefact: only the whole sentence
    counts."""
    frags = [f for f in L.split_fragments(claim_text) if f]

    def own(item):
        q = _quote(item)
        return any(f in q or (snap.is_page(item) and q in f) for f in frags)

    quoted = [r for r in refs if _quote(r)]
    return bool(quoted) and all(own(r) for r in quoted)


def _ref_failure(snap, refs):
    for item in refs:
        why = snap.check_ref(item)
        if why:
            label = item.get("ref") if isinstance(item, dict) else item
            return why if label is None else f"{label}: {why}"
    return None


def _overlap(xs, ys):
    """Whether a half-open interval of xs overlaps one of ys, in one pass over both sorted."""
    reach = [-1, -1]
    for s, e, side in sorted([(s, e, 0) for s, e in xs] + [(s, e, 1) for s, e in ys]):
        if reach[1 - side] > s:
            return True
        reach[side] = max(reach[side], e)
    return False


def _same_statement(snap, a, b):
    """One sentence twice, or quotes found at overlapping places: in one file, or in one line copied to two pages."""
    if _quote(a) and _quote(a) == _quote(b):
        return True
    x, y = snap.places(a), snap.places(b)
    return any(_overlap(x[k], y[k]) for k in x.keys() & y.keys())


def _page_gone(item, claim_text):
    """A status can only be a side when the status is the point: a page the claim names that isn't there."""
    m = URL_REF.match(str(item.get("ref")))
    named = re.sub(r"^https://", "", m["url"]).rstrip("/") if m else ""
    exact = named and re.search(r"(?<![\w.-])" + re.escape(named) + r"(?![\w/-])", claim_text)
    return bool(m) and m["status"][0] in "45" and bool(exact)


def _contradiction_failure(snap, row, claim_text):
    if row.get("confidence") not in CONFIDENCE:
        return "no-confidence"
    sides = row.get("sides") or []
    if len(sides) != 2:
        return "one-sided"
    why = _ref_failure(snap, sides)
    if why:
        return why
    if not _quote(sides[0]) and not _quote(sides[1]):
        return "one-sided"
    for side in sides:
        if not _quote(side) and not _page_gone(side, claim_text):
            return f"{side.get('ref')}: no-quote"
        if snap.unplaced(side):
            return f"{side.get('ref')}: quote-not-unique"
    return "one-sided" if _same_statement(snap, *sides) else _ref_failure(snap, row.get("refs") or [])


def _evidence_failure(snap, claim_text, row):
    refs = row["refs"]  # gate.py has refused an artefact without refs
    why = _ref_failure(snap, refs)
    if why:
        return why
    if not any(_quote(r) for r in refs):
        return "no-quote"
    return "restated" if restated(claim_text, refs, snap) else None


def _other_refs(row, prove_row, disprove_row):
    """The references G3-contradicted and G3-evidenced don't read."""
    prove_refs, disprove_refs = prove_row.get("refs") or [], disprove_row.get("refs") or []
    if row["verdict"] == "CONTRADICTED":
        return prove_refs
    return disprove_refs if row["verdict"] == "EVIDENCED" else prove_refs + disprove_refs


def _not_run(detail):
    return [_gate("G3-contradicted", "hard", "n/a", detail=detail), _gate("G3-evidenced", "soft", "n/a", detail=detail),
            _gate("G3-other", "soft", "n/a", detail=detail)]


def g3_references(run, rows, rules=(), imported=False):
    if imported:
        return _not_run("imported run: free-form references, gated by hand")
    snap = Snapshot(run, rules)
    claims, prove, disprove = (V.load_jsonl(pathlib.Path(run) / f) for f in ("claims.jsonl", "prove.jsonl", "disprove.jsonl"))
    shown = [r for r in rows if not r["withdrawn"]]
    unruled = [r for r in shown if not r["ruled"]]
    bad_c = {r["id"]: _contradiction_failure(snap, disprove[r["id"]], claims[r["id"]]["claim"]) for r in shown if r["verdict"] == "CONTRADICTED"}
    bad_e = {r["id"]: _evidence_failure(snap, claims[r["id"]]["claim"], prove[r["id"]]) for r in unruled if r["verdict"] == "EVIDENCED"}
    bad_o = {r["id"]: _ref_failure(snap, _other_refs(r, prove[r["id"]], disprove[r["id"]])) for r in unruled}

    def build(gid, kind, checked):
        failed = {i: why for i, why in checked.items() if why}
        return _gate(gid, kind, "fail" if failed else "pass", {"rows": len(checked), "failing": len(failed)}, sorted(failed),
                     reasons=failed)

    return [build("G3-contradicted", "hard", bad_c), build("G3-evidenced", "soft", bad_e), build("G3-other", "soft", bad_o)]


def _own_lines(claim, files):
    """The text at the claim's locators, order-free, or None if a locator can't be read."""
    parts = []
    for s in claim["sources"]:
        m = LOCATOR.match(s["locator"])
        if not m or m.group(1) not in files:
            return None
        lines = files[m.group(1)]
        for a, b in LINE_RANGE.findall(m.group(2)):
            if int(b or a) > len(lines):
                return None
            parts.append("\n".join(lines[int(a) - 1:int(b or a)]))
    return sorted(parts)


def _check_outcomes(row):
    return sorted(json.dumps([c.get(k) for k in CHECK_FIELDS]) for c in (row or {}).get("checks", []))


def _snapshot_lines(run):
    folder = pathlib.Path(run) / "sources"
    if not folder.is_dir():
        return None
    return {p.name: p.read_text(encoding="utf-8", errors="replace").split("\n") for p in folder.iterdir() if p.is_file()}


def _grader_verdicts(run, low_rule):
    """The passes' own verdicts, without rulings or private records. Withdrawn claims are left out."""
    claims, prove, disprove = (V.load_jsonl(run / f) for f in ("claims.jsonl", "prove.jsonl", "disprove.jsonl"))
    gone = {i for i, r in V.load_json(run / "judge.json").items() if r.get("verdict") == V.WITHDRAWN}
    return {r["id"]: r["verdict"] for r in V.verdicts(list(claims), prove, disprove, None, low_rule) if r["id"] not in gone}


def _flip_limit(rate, stable):
    return max(math.floor(rate * FLIP_MARGIN * stable + ROUNDING), FLIP_FLOOR)


def g4_stability(run, baseline, flip_rate, low_rule="confidence-field"):
    if baseline is None:
        return _gate("G4", "soft", "n/a", detail="no published baseline")
    run, baseline = pathlib.Path(run), pathlib.Path(baseline)
    files_now, files_then = _snapshot_lines(run), _snapshot_lines(baseline)
    if files_now is None or files_then is None:
        return _gate("G4", "soft", "n/a", detail="no snapshots to compare own lines")

    now, then = _grader_verdicts(run, low_rule), _grader_verdicts(baseline, low_rule)
    claims_now, claims_then = V.load_jsonl(run / "claims.jsonl"), V.load_jsonl(baseline / "claims.jsonl")
    carried = [i for i in now if i in then]
    same_lines = [i for i in carried if (own := _own_lines(claims_now[i], files_now)) is not None
                  and own == _own_lines(claims_then[i], files_then)]
    moved = [i for i in carried if now[i] != then[i]]
    numbers = {"carried": len(carried), "same_lines": len(same_lines), "all_moves": len(moved),
               "evidence_moves": sum(1 for i in moved if {now[i], then[i]} == EVIDENCE_WORDS),
               "new_contradictions": sum(1 for i, v in now.items() if v == "CONTRADICTED" and then.get(i) != v)}
    if not (run / "checks.jsonl").exists() or not (baseline / "checks.jsonl").exists():
        return _gate("G4", "soft", "n/a", numbers, detail="no check rows to compare")
    checks_now, checks_then = V.load_jsonl(run / "checks.jsonl"), V.load_jsonl(baseline / "checks.jsonl")
    stable = [i for i in same_lines if _check_outcomes(checks_now.get(i)) == _check_outcomes(checks_then.get(i))]
    flipped = [i for i in stable if now[i] != then[i]]
    numbers.update(stable=len(stable), flipped=len(flipped))
    if len(stable) <= FLIP_FLOOR:
        return _gate("G4", "soft", "n/a", numbers, detail="too few unchanged claims for the gate to fail")
    if flip_rate is None:
        return _gate("G4", "soft", "n/a", numbers, detail="no measured flip rate for this model and prompt")
    numbers["limit"] = _flip_limit(flip_rate, len(stable))
    failed = len(flipped) > numbers["limit"]
    return _gate("G4", "soft", "fail" if failed else "pass", numbers, sorted(flipped) if failed else ())


def g5_lister(run):
    run = pathlib.Path(run)
    path = run / "lister-rejects.jsonl"
    if not path.exists():
        return _gate("G5", "soft", "n/a", detail="no lister-rejects.jsonl")
    rejects = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    accepted = sum(1 for c in V.load_jsonl(run / "claims.jsonl").values() if c.get("status") in ("new", "reworded"))
    proposals = accepted + len(rejects)
    numbers = {"proposals": proposals, "rejects": len(rejects),
               "by_reason": dict(sorted(collections.Counter(r["reason"] for r in rejects).items()))}
    failed = proposals > 0 and len(rejects) / proposals > REJECT_LIMIT
    return _gate("G5", "soft", "fail" if failed else "pass", numbers,
                 in_excluded_block=[r["proposed_text"] for r in rejects if r["reason"] == "in-excluded-block"])


def _assertion(gid, checks):
    """One assertion row over several checks, which return (ok, detail). A check that can't read its file has failed."""
    results = []
    for fn in checks:
        try:
            results.append(fn())
        except BAD_INPUT as exc:
            results.append((False, f"{type(exc).__name__}: {exc}"))
    return _gate(gid, "assertion", "pass" if all(ok for ok, _ in results) else "fail",
                 detail="; ".join(detail for ok, detail in results if not ok))


def _lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _bad_refs(items):
    if items is None:
        return False
    return not isinstance(items, list) or any(not isinstance(r, str) and not (
        isinstance(r, dict) and isinstance(r.get("ref"), str) and isinstance(r.get("quote"), (str, type(None)))) for r in items)


def _bad_claim(row):
    sources = row.get("sources")
    return not isinstance(row.get("claim"), str) or not isinstance(sources, list) or any(
        not isinstance(s, dict) or not isinstance(s.get("url"), str) or not isinstance(s.get("locator"), str) for s in sources)


def _bad_pass_row(row):
    return _bad_refs(row.get("refs")) or _bad_refs(row.get("sides"))


def _bad_check_row(row):
    checks = row.get("checks")
    return not isinstance(checks, list) or any(not isinstance(c, dict) for c in checks)


def _bad_reject(row):
    return not isinstance(row.get("reason"), str) or not isinstance(row.get("proposed_text"), str)


ROW_CHECKS = (("claims.jsonl", _bad_claim), ("prove.jsonl", _bad_pass_row), ("disprove.jsonl", _bad_pass_row),
              ("checks.jsonl", _bad_check_row), ("lister-rejects.jsonl", _bad_reject))


def _rows_readable(folder):
    """Every row a gate or the merge will read is the right shape, and can be written back out."""
    bad = []
    for name, is_bad in ROW_CHECKS:
        if (folder / name).exists():
            for n, row in enumerate(_lines(folder / name), 1):
                if not isinstance(row, dict) or is_bad(row):
                    bad.append(f"{name}:{n}")
    return not bad, f"rows of the wrong shape {bad[:10]}"


def _fetches_readable(run):
    cache = V.load_json(run / "http-cache.json")
    path = run / "tool-fetches.json"
    tools = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    good = isinstance(cache, dict) and all(isinstance(e, dict) for e in cache.values()) \
        and isinstance(tools, list) and all(isinstance(f, dict) and "url" in f for f in tools)
    return good, "the fetch records are the wrong shape"


def _new_ids_unused(run, published):
    issued = V.load_jsonl(published / "claims.jsonl")
    reused = [c["id"] for c in _lines(run / "claims.jsonl") if c.get("status") == "new" and c["id"] in issued]
    return not reused, f"new ids already published {reused[:10]}"


def _merges(run, low_rule):
    """What the gates pass has to merge, so try it. Nothing is written."""
    M.build_files(run, "r-gate-check", str(V.load_json(run / "run.json").get("domain")), low_rule)
    return True, ""


def _rulings_readable(run):
    judge = V.load_json(run / "judge.json")
    bad = [i for i, r in judge.items() if not isinstance(r, dict) or not isinstance(r.get("verdict"), str)]
    return not bad, f"judge.json rows without a verdict {bad[:10]}"


def _bodies_match(run):
    folder = run / "http-bodies"
    if not folder.is_dir():
        return True, ""
    bad = [p.name for p in folder.iterdir() if hashlib.sha256(p.read_bytes()).hexdigest() != p.name]
    return not bad, f"bodies that don't match their hash {bad[:10]}"


def _assertions(run, baseline, previous, imported, low_rule):
    coverage = [lambda: K.gate_claims(run), lambda: _rulings_readable(run), lambda: _rows_readable(run), lambda: _merges(run, low_rule)]
    for name in ("prove", "disprove"):
        coverage += [lambda n=name: K.gate_same_ids(run, f"{n}.jsonl"), lambda n=name: K.gate_pass_values(run, n)]
    if (run / "checks.jsonl").exists():
        coverage.append(lambda: K.gate_same_ids(run, "checks.jsonl"))
    integrity = [lambda: K.gate_run_json(run), lambda: _bodies_match(run), lambda: _fetches_readable(run)]
    if not imported or (run / "sources").is_dir():  # imports publish hashes, not the snapshots
        integrity.append(lambda: K.gate_sources(run))
    gates = [_assertion("A1", coverage), _assertion("A2", integrity)]
    source = previous if previous is not None else baseline
    if source is not None:
        carried = [lambda: K.gate_previous(run, pathlib.Path(source))]
        if baseline is not None and previous is not None:
            carried.append(lambda: _new_ids_unused(run, pathlib.Path(baseline)))
        gates.append(_assertion("carried-ids", carried))
    if baseline is not None:
        base = pathlib.Path(baseline)
        gates.append(_assertion("baseline", [lambda: _rows_readable(base), lambda: _rulings_readable(base)]))
    if (run / "private-evidence.json").exists():
        gates.append(_assertion("private-evidence", [lambda: K.gate_private(run)]))
    return gates


def _guarded(gid, gate_rows):
    """A gate that can't read what it needs has failed, and that blocks the run."""
    try:
        return gate_rows()
    except BAD_INPUT as exc:
        return [_gate(gid, "assertion", "fail", detail=f"{type(exc).__name__}: {exc}")]


def _outcome(gates):
    failed = {g["kind"] for g in gates if g["result"] == "fail"}
    if failed & {"assertion", "hard"}:
        return "blocked"
    return "needs-acknowledgement" if failed else "pass"


def _run_json(run):
    try:
        data = V.load_json(run / "run.json")
    except BAD_INPUT:
        return {}
    return data if isinstance(data, dict) else {}


def run_gates(run_dir, baseline=None, flip_rate=None, rules=None, imported=None, low_rule="confidence-field", previous=None):
    """`previous` is where the ids came from, the published `baseline` unless given; G4 always compares with `baseline`."""
    run = pathlib.Path(run_dir)
    run_json = _run_json(run)
    imported = bool(run_json.get("imported")) if imported is None else imported
    rules = (run_json.get("exclusions") or ()) if rules is None else rules
    gates = _assertions(run, baseline, previous, imported, low_rule)
    if any(g["result"] == "fail" for g in gates):
        detail = "not run: an assertion failed"
        gates += _not_run(detail) + [_gate("G4", "soft", "n/a", detail=detail), _gate("G5", "soft", "n/a", detail=detail)]
    else:
        gates += _guarded("G3", lambda: g3_references(run, V.load_run(run, low_rule), rules, imported))
        gates += _guarded("G4", lambda: [g4_stability(run, baseline, flip_rate, low_rule)])
        gates += _guarded("G5", lambda: [g5_lister(run)])
    out = {"version": VERSION, "outcome": _outcome(gates), "gates": gates}
    if imported:
        out["imported"] = True
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir")
    ap.add_argument("--baseline", help="the published run, for G4")
    ap.add_argument("--previous", help="the run the ids were carried from, when it isn't the baseline")
    ap.add_argument("--flip-rate", type=float)
    ap.add_argument("--rules", help="the domain's exclusion rules, a JSON list; run.json's exclusions otherwise")
    ap.add_argument("--low-rule", default="confidence-field", choices=V.LOW_RULES)
    ap.add_argument("--out", help="write gates.json here")
    a = ap.parse_args(argv)
    rules = json.loads(pathlib.Path(a.rules).read_text(encoding="utf-8")) if a.rules else None
    result = run_gates(a.run_dir, a.baseline, a.flip_rate, rules, low_rule=a.low_rule, previous=a.previous)
    if a.out:
        pathlib.Path(a.out).write_text(json.dumps(result, indent=1) + "\n", encoding="ascii")
    for g in result["gates"]:
        print(g["result"].upper().ljust(5), g["id"], json.dumps(g["detail"] or g["numbers"]))
    print(result["outcome"])
    return 0 if result["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
