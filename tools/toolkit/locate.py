"""Find a claim word for word in a run's saved sources (VR-03), skip excluded blocks (R-03.4), carry ids (VR-06).

Generalised from the sixth onedroid.ai run's lister scripts (trilix-onedroid-business
ideas/claims-audit-onedroid-2026-10-28-r6/work/lib.py and build.py): the same normalisation and locator format, with
no hardcoded paths, source list or domain.

Normalisation: runs of whitespace are one space; in .html files tags are dropped and entities decoded; in every other
file a ">" blockquote marker at the start of a line is ignored. A claim made of several fragments is joined with
" [...] " and must occur in order in ONE source; if no source has the fragments in order, a source holding all of them
in any order still counts (the r6 run's C-209 case). Lines inside an excluded block read as a single space.

Exclusion rules (a JSON list, per domain):
    {"kind": "markers", "files": "<glob>", "start": "claims-register:start", "end": "claims-register:end"}
    {"kind": "heading", "files": "<glob>", "start_prefix": "...", "end_before_prefix": "# PAGE:", "separator_prefix": "====="}
Stdlib only. Nothing here judges a claim.
"""
import bisect
import fnmatch
import html as htmllib
import pathlib
import re

TOKEN_HTML = re.compile(r"<[^>]*>|&#?\w+;|\s+|[^<&\s]+|[<&]")
TOKEN_TEXT = re.compile(r"\s+|\S+")
MD_HEADING = re.compile(r"^#{1,6}\s+(.*\S)\s*$")
HTML_HEADING = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>")
PAGE_PREFIX = "# PAGE: "
FRAGMENT_JOIN = " [...] "
RULE_KINDS = ("markers", "heading")


def norm_claim(text):
    return re.sub(r"\s+", " ", text).strip()


def split_fragments(text):
    return [norm_claim(x) for x in text.split(FRAGMENT_JOIN)]


def _marker_ranges(lines, rule):
    """Every marked block. An end before any start means nothing; a block left open runs to the end of the file, because
    showing a claim as gone is visible and treating register text as the page's own is not."""
    out, start = [], None
    for i, line in enumerate(lines, 1):
        if start is None and rule["start"] in line:
            start = i
        if start is not None and rule["end"] in line:
            out.append((start, i))
            start = None
    return out + [(start, len(lines))] if start else out


def _heading_range(lines, rule):
    # Exactly the r6 lib.register_range fallback, including its index arithmetic, so the excluded lines are the ones
    # the published sixth run excluded.
    start = None
    for i, line in enumerate(lines, 1):
        if line.startswith(rule["start_prefix"]):
            start = i
            break
    if not start:
        return None
    for j in range(start, len(lines)):
        if lines[j].startswith(rule["end_before_prefix"]) and j > start:
            k = j - 1
            while k > start and not lines[k].strip().startswith(rule["separator_prefix"]):
                k -= 1
            e = k - 1
            while lines[e - 1].strip() == "" and e > start:
                e -= 1
            return (start, e)
    return None


def check_rules(rules):
    for r in rules:
        if r.get("kind") not in RULE_KINDS:
            raise ValueError(f"unknown exclusion rule kind {r.get('kind')!r}")
    return list(rules)


class Source:
    def __init__(self, fname, raw, domain=None, rules=(), page_bundle=None, is_html=None):
        self.fname = fname
        self.raw = raw
        self.lines = raw.split("\n")
        self.is_html = fname.endswith(".html") if is_html is None else is_html
        self.page_bundle = fname.startswith("llms-full") if page_bundle is None else page_bundle
        self.domain = domain
        self.excluded = []
        for rule in check_rules(rules):
            if not fnmatch.fnmatch(fname.rsplit("/", 1)[-1], rule.get("files", "*")):
                continue
            if rule["kind"] == "markers":
                self.excluded += _marker_ranges(self.lines, rule)
            else:
                rng = _heading_range(self.lines, rule)
                if rng:
                    self.excluded.append(rng)
        self._build()
        self._index_pages()

    def _is_excluded(self, ln):
        return any(a <= ln <= b for a, b in self.excluded)

    def _build(self):
        raw = self.raw
        starts = [0] + [m.end() for m in re.finditer("\n", raw)]
        out, lmap = [], []
        for m in (TOKEN_HTML if self.is_html else TOKEN_TEXT).finditer(raw):
            tok, off = m.group(0), m.start()
            ln = bisect.bisect_right(starts, off)
            if self._is_excluded(ln):
                if out and out[-1] != " ":
                    out.append(" ")
                    lmap.append(ln)
                continue
            if self.is_html and tok[0] == "<" and len(tok) > 1:
                continue
            if self.is_html and tok[0] == "&" and len(tok) > 2 and tok[-1] == ";":
                tok = htmllib.unescape(tok)
            if tok.isspace():
                if out and out[-1] != " ":
                    out.append(" ")
                    lmap.append(ln)
                continue
            if not self.is_html and tok == ">" and (off == 0 or raw[off - 1] == "\n"):
                continue
            out.extend(tok)
            lmap.extend([ln] * len(tok))
        self.text = "".join(out)
        self.lmap = lmap

    def _index_pages(self):
        self.page_at, self.head_at = {}, {}
        page = head = None
        for i, line in enumerate(self.lines, 1):
            if self.page_bundle and line.startswith(PAGE_PREFIX):
                page = line[len(PAGE_PREFIX):].strip()
                if self.domain:
                    page = page.replace("https://" + self.domain, "")
                page = page or "/"
                head = None
            elif not self.is_html:
                mm = MD_HEADING.match(line)
                if mm:
                    head = mm.group(1)
            else:
                for hm in HTML_HEADING.finditer(line):
                    t = htmllib.unescape(re.sub(r"<[^>]*>", "", hm.group(1)))
                    head = re.sub(r"\s+", " ", t).strip()
            self.page_at[i] = page
            self.head_at[i] = head

    def _find_all(self, frag):
        found, i = [], self.text.find(frag)
        while i != -1:
            found.append(i)
            i = self.text.find(frag, i + 1)
        return found

    def locate(self, frags):
        """Every (first line, last line) where the fragments occur in order. Empty text occurs nowhere."""
        occ = []
        if not all(frags):
            return occ
        for s in self._find_all(frags[0]):
            e = s + len(frags[0])
            for f in frags[1:]:
                j = self.text.find(f, e)
                if j == -1:
                    return occ  # a later start can't do better
                e = j + len(f)
            occ.append((self.lmap[s], self.lmap[e - 1]))
        return occ

    def spans(self, text):
        """(start, end, first line, last line) of every place the text occurs in the normalised page."""
        return [(s, s + len(text), self.lmap[s], self.lmap[s + len(text) - 1]) for s in self._find_all(text)]

    def line_around(self, start, end):
        """The normalised text of the whole lines a span sits on, and where that text starts."""
        a, b = bisect.bisect_left(self.lmap, self.lmap[start]), bisect.bisect_right(self.lmap, self.lmap[end - 1])
        text = self.text[a:b]
        return text.strip(), a + len(text) - len(text.lstrip())

    def _context(self, line):
        parts = []
        if self.page_at.get(line):
            parts.append("PAGE " + self.page_at[line])
        if self.head_at.get(line):
            parts.append('under "%s"' % self.head_at[line])
        return " (" + "; ".join(parts) + ")" if parts else ""

    def locator(self, l1, l2):
        rng = "L%d" % l1 if l1 == l2 else "L%d-%d" % (l1, l2)
        return "sources/%s %s%s" % (self.fname, rng, self._context(l1))

    def locator_parts(self, parts):
        rngs = ["L%d" % x if x == y else "L%d-%d" % (x, y) for x, y in sorted(set(parts))]
        return "sources/%s %s%s" % (self.fname, ", ".join(rngs), self._context(parts[0][0]))


def occurrences(text, sources):
    """[(url, source, locator)] in source order. Ordered matches first; only when no source has the fragments in order,
    sources holding every fragment in any order."""
    frags = split_fragments(text)
    ordered = [(url, s, s.locator(a, b)) for url, s in sources for a, b in s.locate(frags)]
    if ordered:
        return ordered
    unordered = []
    for url, s in sources:
        parts = []
        for f in frags:
            found = s.locate([f])
            if not found:
                break
            parts.append(found[0])
        else:
            unordered.append((url, s, s.locator_parts(parts)))
    return unordered


def locate_claim(text, sources):
    """The claim's `sources` list: every place it occurs, de-duplicated, in source order."""
    out, seen = [], set()
    for url, _s, loc in occurrences(text, sources):
        if (url, loc) not in seen:
            seen.add((url, loc))
            out.append({"url": url, "locator": loc})
    return out


def in_excluded_block(text, sources):
    """True when the text is word for word in a source once that source's excluded blocks count again."""
    frags = split_fragments(text)
    return any(s.excluded and Source(s.fname, s.raw, s.domain, (), s.page_bundle).locate(frags) for _url, s in sources)


def carry(previous_claims, sources):
    """Previous claims still published word for word -> kept (fresh locators); the rest -> missing (candidates for
    reworded, or absent)."""
    kept, missing = [], []
    for c in previous_claims:
        locs = locate_claim(c["claim"], sources)
        if locs:
            kept.append({"id": c["id"], "claim": c["claim"], "sources": locs, "kind": c["kind"],
                         "checkability": c["checkability"], "status": "kept"})
        else:
            missing.append(c)
    return {"kept": kept, "missing": missing}


def source_table(claims_md):
    """[(url, local file)] from a claims.md sources table, numbered or not, in table order."""
    rows = []
    for line in pathlib.Path(claims_md).read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0].isdigit() and len(cells) >= 3:
            cells = cells[1:]
        if len(cells) >= 2 and cells[0].startswith("http") and cells[1].startswith("sources/"):
            rows.append((cells[0], cells[1][len("sources/"):]))
    return rows


def load_run_sources(run_dir, domain=None, rules=()):
    d = pathlib.Path(run_dir)
    folder, out = (d / "sources").resolve(), []
    for url, fname in source_table(d / "claims.md"):
        path = (folder / fname).resolve()
        if folder not in path.parents:
            raise ValueError(f"claims.md: {fname!r} is outside sources/")
        out.append((url, Source(fname, path.read_text(encoding="utf-8", errors="replace"), domain, rules)))
    return out
