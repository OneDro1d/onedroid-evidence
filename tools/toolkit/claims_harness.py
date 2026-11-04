#!/usr/bin/env python3
"""Claims harness, slice P2b: the audit method as code (HARNESS-SPEC.md, 2026-10-27).

    python3 -I claims_harness.py check <run_dir> [--offline]
    python3 -I claims_harness.py prompt prove|disprove <run_dir>

`check` reads <run_dir>/claims.jsonl, <run_dir>/sources/, optional <run_dir>/repo/ (a read-only clone) and
<run_dir>/run.json, runs every mechanical check each claim's type calls for, and writes <run_dir>/checks.jsonl (one
row per claim, claims order) plus <run_dir>/checks-summary.md. `prompt` writes <run_dir>/prompt-<kind>.md: the
existing prompts/<kind>.md text with the per-claim check block appended (or referenced from checks-for-prompt.md when
the prompt would pass 120k characters).

Rules the code enforces (each has a test in tests/test_harness.py):
  VR-1 one row per claim id, same order, no invented ids.
  VR-2 repo-grep without repo/ says `no-repo`, never `not-found`.
  VR-3 GET only, one request per distinct URL per run (cache in <run_dir>/http-cache.json), status + body sha256
       recorded, one retry at most, hosts outside run.json.hosts refused with `error:host-not-allowed`, a bare
       `/path` resolved only against a host the claim itself names (else `error:no-host`).
  VR-4 arithmetic only when both operands sit on the same source page; `consistent` when the computed figure is
       within one unit of the displayed precision or within 1% relative; `inconsistent` beyond that.
  VR-5 dated lines are quoted whole with file and line; same-year lines on the claim's own pages are included; for
       status claims every line inside a dated block (nearest date above, same page) that carries a claim word is
       quoted with its governing date (the C-097 class: a dated "available by request" under a 2026-10-09 heading).
  VR-6 deterministic: no timestamps in rows, sorted hits, capped lists; same inputs give a byte-identical file.
  VR-7 stdlib only.  VR-8 sources/ and repo/ are read, never executed (no subprocess at all).
  VR-9 the prompt builder appends the check block and the grading sentence; over 120k characters it writes
       checks-for-prompt.md and references it.

Closed status sets: repo-grep / source-grep / repo-file / repo-metadata: found | not-found | no-repo | no-file;
http-get: <int> | error:<reason>; numbers: consistent | inconsistent | not-evaluable.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
USER_AGENT = "Mozilla/5.0 (claims-harness; GET only)"
HTTP_TIMEOUT = 10
MAX_HITS = 12          # per query, source-grep
MAX_REPO_HITS = 60     # per query, repo-grep: first hit per file, code before tests (read-only: 43 code files)
MAX_DATED = 40         # per claim
MAX_QUERIES = 10       # technical tokens per claim
PROMPT_LIMIT = 120_000
GRADE_SENTENCE = ("Grade from the check results first; search further only where a check says not-found or "
                  "could not run.")

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
MONTH_RE = "|".join(MONTHS)
ISO_DATE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
DMY_DATE = re.compile(r"\b(\d{1,2}) (" + MONTH_RE + r")(?:,)? (20\d\d)\b")
MDY_DATE = re.compile(r"\b(" + MONTH_RE + r") (\d{1,2}),? (20\d\d)\b")
MY_DATE = re.compile(r"\b(" + MONTH_RE + r") (20\d\d)\b")
ANY_YEAR = re.compile(r"\b(20\d\d)\b")

STOPWORDS = set("""about above after again against all also among and another any are around because been before
being below between both but can cannot could did does doing done down during each either every for from further
had has have having here how into its itself just like made make makes many may might more most much must need
never not nothing now off once one only other others ought our ours out over own same several shall she should
since some something still such than that the their theirs them then there these they this those through thus
under until upon very was were what when where whether which while who whom whose will with within without would
your yours each every their there these those about which while where there before after because during under
over again only also never these those than then them they this that with from into onto upon about across along
whose users customer customers company pages page sites site runs running using used uses use give gives given
agent agents system systems check checks claim claims work works working team teams tester testing test tests
onedroid argus""".split())

TECH_PATTERNS = [
    ("backtick", re.compile(r"`([^`]{2,80})`")),
    ("quoted", re.compile(r"[\"“]([^\"”]{4,80})[\"”]")),
    ("argus-cmd", re.compile(r"\bargus(?: [a-z][a-z-]*){1,2}\b")),
    ("flag", re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*\b")),
    ("snake", re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")),
    ("hyphen", re.compile(r"\b[a-z]+(?:-[a-z0-9]+)+\b")),
    ("version", re.compile(r"\bv?\d+\.\d+\.\d+\b")),
    ("exit", re.compile(r"\bexit(?:s|ed)?(?: code)? (\d+)\b")),
    ("env", re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")),
]
URL_RE = re.compile(r"\bhttps?://[^\s\"'()\[\]]+|(?<![\w@/])(?:[a-z0-9-]+\.)+(?:ai|com|io|org|net|be|dev)"
                    r"(?:/[^\s\"'()\[\],;]*)?")
PLACEHOLDER_RE = re.compile(r"<[^>]*>|\{[^}]*\}")
QUANTIFIER_RE = re.compile(r"\b(every|only|never|no|all|any|each|nobody|nothing) ([a-z][a-z-]{2,})\b", re.I)
PATH_RE = re.compile(r"(?<![\w/.:-])(?:[\w.-]+/)+[\w.-]+(?![\w/])")
BARE_PATH_RE = re.compile(r"(?<![\w/.:])/(?:[a-z0-9_<>.-]+/?)+(?![\w/])")
NUMBER_RE = re.compile(r"(?<![\w.])(\$?\d[\d,]*(?:\.\d+)?)\s?(%|million|thousand|billion|k\b|M\b|×|x\b)?")
PERCENT_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?%")

NEGATIVE_WORDS = re.compile(r"\b(never|no|not|only|without|nobody|nothing|none)\b", re.I)
LICENCE_WORDS = re.compile(r"\b(MIT|Apache(?:-2\.0)?|GPL|AGPL|BSD|MPL|open[- ]source[d]?|licen[cs]e[d]?)\b", re.I)
METADATA_WORDS = re.compile(r"\b(public since|created|stars?|contributors?|forks?|open[- ]sourced|since \d|"
                            r"pushed|last commit|repository has been public)\b", re.I)
VERSION_WORDS = re.compile(r"\b(version|release[d]?)\b", re.I)
COMMAND_WORDS = re.compile(r"\b(command|flag|cli|tool|endpoint|subcommand)\b", re.I)


# ----------------------------------------------------------------------------------------------- loading

def read_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_run(run_dir):
    p = os.path.join(run_dir, "run.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {"publisher": "", "domain": "", "hosts": [], "repo_commit": "", "fetched_at": ""}


def is_text(data: bytes) -> bool:
    return b"\x00" not in data[:4096]


def load_tree(root, skip_dirs=(".git", "node_modules", "vendor")):
    """Every text file under root, as {relative path: [lines]}, read only."""
    tree = {}
    if not root or not os.path.isdir(root):
        return tree
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs)
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            try:
                with open(full, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            if not is_text(data):
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            tree[rel] = data.decode("utf-8", "replace").split("\n")
    return tree


def source_map(run_dir):
    """URL -> sources/<file> from the lister's table in claims.md (| url | sources/file | status | bytes | sha256 |)."""
    mapping = {}
    cm = os.path.join(run_dir, "claims.md")
    if os.path.exists(cm):
        with open(cm, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\|\s*(https?://\S+)\s*\|\s*(sources/\S+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([0-9a-f]{64})", line)
                if m:
                    mapping[m.group(1).rstrip("/")] = m.group(2)[len("sources/"):]
                    SAVED_SHA[m.group(1).rstrip("/")] = m.group(5)
                    continue
                m = re.match(r"\|\s*(https?://\S+)\s*\|\s*(sources/\S+)\s*\|", line)
                if m:
                    mapping[m.group(1).rstrip("/")] = m.group(2)[len("sources/"):]
    return mapping


SAVED_SHA = {}

# Negative claims: the wording that would contradict them. A hand-kept table, small on purpose; each hit is a
# line for the disprove pass to read, never a verdict.
OPPOSITES = {
    "anyone": ["by request", "needs an account", "invite", "waitlist", "contact us", "talk to us"],
    "sign up": ["by request", "invite", "waitlist"],
    "self-serve": ["by request", "contact us", "talk to us"],
    "read-only": ["writes to", "write access", "cleanup"],
    "no account": ["account"],
    "without an account": ["account"],
    "no cluster": ["kubernetes cluster", "needs a cluster"],
    "does not re-run": ["re-runs", "re-executes"],
    "never": ["may", "can"],
    "free": ["per seat", "per month", "$"],
}


def page_sections(lines):
    """[(start_line_1based, end_line_1based_exclusive, page_url)] from '# PAGE: <url>' markers; one section if none."""
    marks = [(i + 1, line[len("# PAGE:"):].strip()) for i, line in enumerate(lines) if line.startswith("# PAGE:")]
    if not marks:
        return [(1, len(lines) + 1, "")]
    out = []
    for k, (start, url) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(lines) + 1
        out.append((start, end, url))
    return out


# ----------------------------------------------------------------------------------------------- detectors

def normalise_token(tok: str) -> str:
    return tok.strip().strip(".,;:")


def technical_tokens(text: str):
    """[(kind, token)] in order of appearance, de-duplicated. URLs are removed first so hosts never become paths."""
    found = []
    seen = set()
    urls = [m.group(0) for m in URL_RE.finditer(text)]
    scrubbed = URL_RE.sub(" ", text)
    for kind, rx in TECH_PATTERNS:
        for m in rx.finditer(scrubbed):
            tok = normalise_token(m.group(1) if m.groups() else m.group(0))
            if kind == "exit":
                tok = "exit " + m.group(1)
            if kind == "hyphen" and tok in ("e-mail", "re-run", "pre-installed", "built-in", "self-hosted",
                                            "on-prem", "day-one", "long-lived", "third-party", "end-to-end"):
                continue
            if len(tok) < 3 or tok in seen:
                continue
            seen.add(tok)
            found.append((kind, tok))
    for m in PATH_RE.finditer(scrubbed):
        tok = normalise_token(m.group(0))
        if tok in seen or re.fullmatch(r"[\d./]+", tok) or "/" not in tok:
            continue
        # a path needs a letter and must not be a date or a fraction
        if not re.search(r"[A-Za-z]", tok):
            continue
        seen.add(tok)
        found.append(("path", tok))
    return found, urls


def content_words(text: str, min_len=5):
    words = []
    for w in re.findall(r"[A-Za-z][A-Za-z-]+", URL_RE.sub(" ", text)):
        lw = w.lower().strip("-")
        if len(lw) >= min_len and lw not in STOPWORDS and lw not in words:
            words.append(lw)
    return words


def claim_dates(text: str):
    """(set of textual forms to grep for, set of years named)."""
    forms, years = set(), set()
    for y, mo, d in ISO_DATE.findall(text):
        years.add(y)
        forms.add(f"{y}-{mo}-{d}")
        month = MONTHS[int(mo) - 1]
        forms.add(f"{int(d)} {month} {y}")
        forms.add(f"{month} {int(d)}, {y}")
    for d, month, y in DMY_DATE.findall(text):
        years.add(y)
        forms.add(f"{int(d)} {month} {y}")
        forms.add(f"{month} {int(d)}, {y}")
        forms.add(f"{y}-{MONTHS.index(month) + 1:02d}-{int(d):02d}")
    for month, d, y in MDY_DATE.findall(text):
        years.add(y)
        forms.add(f"{int(d)} {month} {y}")
        forms.add(f"{month} {int(d)}, {y}")
        forms.add(f"{y}-{MONTHS.index(month) + 1:02d}-{int(d):02d}")
    for month, y in MY_DATE.findall(text):
        years.add(y)
        forms.add(f"{month} {y}")
    for y in ANY_YEAR.findall(text):
        years.add(y)
    return forms, years


def detect_types(claim: dict):
    text = claim.get("claim", "")
    kind = claim.get("kind", "")
    toks, urls = technical_tokens(text)
    types = []
    kinds = {k for k, _ in toks}
    if kinds & {"backtick", "argus-cmd", "flag", "snake", "exit", "env"} or COMMAND_WORDS.search(text):
        types.append("command")
    if urls or BARE_PATH_RE.search(URL_RE.sub(" ", text)):
        types.append("url")
    forms, _years = claim_dates(text)
    if forms:
        types.append("date")
    if PERCENT_RE.search(text) or kind in ("number", "comparison") or re.search(
            r"\d[\d,]*(?:\.\d+)?\s?(%|\$|million|thousand|k\b)|\$\s?\d|\b(of|out of)\b \d|\d+ (of|out of) ", text):
        types.append("number")
    if LICENCE_WORDS.search(text) or kind == "licence":
        types.append("licence")
    if METADATA_WORDS.search(text):
        types.append("repo-metadata")
    if "version" in kinds or VERSION_WORDS.search(text):
        types.append("version")
    if NEGATIVE_WORDS.search(text):
        types.append("policy")
    if "path" in kinds:
        types.append("path")
    if not types:
        types.append("other")
    return types, toks, urls


# ----------------------------------------------------------------------------------------------- checks

def is_test_path(path: str) -> bool:
    return "_test." in path or "/test" in path or path.startswith("test")


_LOWER = {}   # id(tree) -> {path: [lowercased lines]}, built once per tree: lowering per query made a 59-page run take minutes


def lower_lines(tree: dict, path: str):
    cache = _LOWER.setdefault(id(tree), {})
    if path not in cache:
        cache[path] = [l.lower() for l in tree[path]]
    return cache[path]


def grep_tree(tree: dict, query: str, prefix: str, cap: int, per_file=False):
    """Fixed-string grep, case-sensitive first, then insensitive. Returns (hits, total, mode).
    With per_file the list holds the first hit of each file, code files before test files, so a capped list still
    names every file that matters (the read-only case: 99 hits in 40 files must still show verifysql.go)."""
    # per_file (the repo): identifiers vary in case (readOnly, READ-ONLY), so the file list is always
    # case-insensitive and the mode reports whether an exact match exists anywhere
    modes = ("ci",) if per_file else ("exact", "ci")
    for mode in modes:
        q = query if mode == "exact" else query.lower()
        all_hits, total, exact_total = [], 0, 0
        for path in sorted(tree):
            lines = tree[path] if mode == "exact" else lower_lines(tree, path)
            for i, hay in enumerate(lines):
                line = tree[path][i]
                if q in hay:
                    total += 1
                    all_hits.append((path, i + 1))
                    if query in line:
                        exact_total += 1
        if total:
            if per_file:
                first = {}
                for path, ln in all_hits:
                    first.setdefault(path, ln)
                ordered = sorted(first.items(), key=lambda kv: (is_test_path(kv[0]), kv[0]))
                hits = [f"{prefix}{p}#L{ln}" for p, ln in ordered[:cap]]
                return hits, total, "exact" if exact_total else "ci"
            hits = [f"{prefix}{p}#L{ln}" for p, ln in all_hits[:cap]]
            return hits, total, mode
    return [], 0, "exact"


def check_repo_grep(repo_tree, query):
    if repo_tree is None:
        return {"check": "repo-grep", "query": query, "hits": [], "status": "no-repo"}
    hits, total, mode = grep_tree(repo_tree, query, "", MAX_REPO_HITS, per_file=True)
    if not total and "/" in query:
        # a path token: files under that path count as hits (the directory itself has no lines to grep)
        prefix = query.strip("/") + "/"
        paths = [p for p in sorted(repo_tree) if p.startswith(prefix) or p == query.strip("/")]
        if paths:
            return {"check": "repo-grep", "query": query, "hits": paths[:MAX_REPO_HITS], "status": "found",
                    "match": "path"}
    row = {"check": "repo-grep", "query": query, "hits": hits, "status": "found" if total else "not-found"}
    if total > len(hits):
        row["total"] = total
        row["listed"] = "first hit per file, code before tests"
    if total and mode == "ci":
        row["match"] = "case-insensitive"
    return row


def check_source_grep(src_tree, query):
    hits, total, mode = grep_tree(src_tree, query, "sources/", MAX_HITS)
    row = {"check": "source-grep", "query": query, "hits": hits, "status": "found" if total else "not-found"}
    if total > len(hits):
        row["total"] = total
    if total and mode == "ci":
        row["match"] = "case-insensitive"
    return row


def check_repo_files(repo_tree, pattern: re.Pattern, label: str):
    if repo_tree is None:
        return {"check": "repo-file", "query": label, "hits": [], "status": "no-repo"}
    hits = []
    for path in sorted(repo_tree):
        if pattern.search(os.path.basename(path)):
            first = next((l.strip() for l in repo_tree[path] if l.strip()), "")
            hits.append(f"{path}: {first[:80]}")
    return {"check": "repo-file", "query": label, "hits": hits[:MAX_REPO_HITS],
            "status": "found" if hits else "not-found"}


LICENCE_FILE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE)(\.|$)", re.I)
METADATA_FIELDS = ["full_name", "private", "visibility", "created_at", "pushed_at", "updated_at", "default_branch",
                   "stargazers_count", "forks_count", "open_issues_count", "subscribers_count", "archived"]


def check_metadata(run_dir):
    p = os.path.join(run_dir, "sources", "github-repo.json")
    if not os.path.exists(p):
        return {"check": "repo-metadata", "query": "sources/github-repo.json", "fields": {}, "status": "no-file"}
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        return {"check": "repo-metadata", "query": "sources/github-repo.json", "fields": {},
                "status": f"error:{type(e).__name__}"}
    fields = {k: d.get(k) for k in METADATA_FIELDS if k in d}
    lic = d.get("license") or {}
    if isinstance(lic, dict):
        fields["license.spdx_id"] = lic.get("spdx_id")
    return {"check": "repo-metadata", "query": "sources/github-repo.json", "fields": fields, "status": "found"}


class HttpClient:
    """GET only. One request per distinct URL per run; results cached in <run_dir>/http-cache.json so a second run
    on the same inputs is byte-identical. `fetch` is injectable for tests (must never be called for refused hosts)."""

    def __init__(self, run_dir, hosts, offline=False, fetch=None, connector_hosts=()):
        self.hosts = {h.lower() for h in hosts}
        self.connector_hosts = {h.lower() for h in connector_hosts}  # read through a connector, cached, never fetched
        self.offline = offline
        self.fetch = fetch or (lambda url: default_fetch(url, self.hosts))
        self.cache_path = os.path.join(run_dir, "http-cache.json")
        self.cache = {}
        self.requests_made = 0
        if os.path.exists(self.cache_path):
            with open(self.cache_path, encoding="utf-8") as f:
                self.cache = json.load(f)

    def allowed(self, host):
        return host.lower() in self.hosts

    def get(self, url):
        row = {"check": "http-get", "url": url}
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            row["status"] = "error:not-a-url"
            return row
        connector = parts.hostname.lower() in self.connector_hosts
        if not connector and not self.allowed(parts.hostname):
            row["status"] = "error:host-not-allowed"
            return row
        if url in self.cache:
            for k in ("status", "sha256", "bytes", "final_url", "redirect"):
                if k in self.cache[url]:
                    row[k] = self.cache[url][k]
            return row
        if connector:
            row["status"] = "error:connector-only"
            return row
        if self.offline:
            row["status"] = "error:offline"
            return row
        result = None
        for _attempt in (1, 2):
            self.requests_made += 1
            result = self.fetch(url)
            if isinstance(result.get("status"), int) and result["status"] < 500:
                break
        self.cache[url] = result
        for k in ("status", "sha256", "bytes", "final_url", "redirect"):
            if k in result:
                row[k] = result[k]
        return row

    def save(self):
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, indent=1, sort_keys=True)


class RedirectRefused(Exception):
    def __init__(self, target):
        super().__init__(target)
        self.target = target


class _OneRedirect(urllib.request.HTTPRedirectHandler):
    """Follow one redirect, and only to a host in run.json.hosts."""
    max_redirections = 1

    def __init__(self, hosts):
        super().__init__()
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = (urllib.parse.urlsplit(newurl).hostname or "").lower()
        if self.hosts is not None and host not in self.hosts:
            raise RedirectRefused(newurl)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.add_header("User-Agent", USER_AGENT)
        return new


def default_fetch(url, hosts=None):
    opener = urllib.request.build_opener(_OneRedirect(hosts))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    try:
        with opener.open(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read()
            out = {"status": int(resp.status), "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                   "final_url": resp.geturl()}
            return out
    except RedirectRefused as e:
        return {"status": "error:redirect-host-not-allowed", "redirect": e.target}
    except urllib.error.HTTPError as e:
        body = e.read() if hasattr(e, "read") else b""
        out = {"status": int(e.code), "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
               "final_url": url}
        loc = e.headers.get("Location") if getattr(e, "headers", None) else None
        if loc:
            out["redirect"] = loc
        return out
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        return {"status": f"error:{type(reason).__name__ if not isinstance(reason, str) else reason}"}
    except (TimeoutError, OSError, ValueError) as e:
        return {"status": f"error:{type(e).__name__}"}


def resolve_urls(text, urls, hosts):
    """Full URLs as given (https assumed when bare); a bare /path only against a host the claim itself names."""
    out = []
    for u in urls:
        u = normalise_token(u).rstrip("/)")
        if not u.startswith("http"):
            u = "https://" + u
        if PLACEHOLDER_RE.search(u):
            out.append(("placeholder", u))
            continue
        if u not in out:
            out.append(u)
    # the host the claim names, longest first so synapse.onedroid.ai wins over onedroid.ai; whole token only
    named_hosts = [h for h in sorted(hosts, key=len, reverse=True)
                   if re.search(r"(?<![\w.-])" + re.escape(h.lower()) + r"(?![\w-])", text.lower())]
    scrubbed = URL_RE.sub(" ", text)
    for m in BARE_PATH_RE.finditer(scrubbed):
        path = m.group(0).rstrip("/.,;:")
        if "<" in path or len(path) < 2:
            continue
        if named_hosts:
            u = "https://" + named_hosts[0] + path
            if u not in out:
                out.append(u)
        else:
            out.append(("no-host", path))
    return out


# ----------------------------------------------------------------------------------------------- dates, numbers

def date_index(src_tree):
    """For each file: list of (line_no, date_text) for lines that carry a date, and the page sections."""
    idx = {}
    for path, lines in src_tree.items():
        dated = []
        for i, line in enumerate(lines):
            m = ISO_DATE.search(line) or DMY_DATE.search(line) or MDY_DATE.search(line)
            if m:
                dated.append((i + 1, m.group(0)))
        idx[path] = {"dated": dated, "pages": page_sections(lines)}
    return idx


def governing_date(idx_entry, line_no, window=40):
    """The nearest dated line at or above line_no inside the same page section, within `window` lines."""
    page = next(((s, e) for s, e, _ in idx_entry["pages"] if s <= line_no < e), None)
    best = None
    for ln, dt in idx_entry["dated"]:
        if ln <= line_no and line_no - ln <= window and (page is None or page[0] <= ln < page[1]):
            best = (ln, dt)
    return best


def claim_pages(claim, smap, src_tree):
    """[(file, start, end)] the claim's own sources resolve to; empty when none resolve."""
    pages = []
    for s in claim.get("sources", []):
        url = (s.get("url") or "").rstrip("/")
        locator = s.get("locator") or ""
        fname = smap.get(url) or smap.get(url.split("#")[0])
        if not fname:
            base = url.rsplit("/", 1)[-1]
            if base in src_tree:
                fname = base
        if not fname or fname not in src_tree:
            continue
        lines = src_tree[fname]
        sections = page_sections(lines)
        m = re.search(r"PAGE (/\S*)", locator)
        if m and len(sections) > 1:
            want = m.group(1).rstrip(":,")
            for st, en, purl in sections:
                if urllib.parse.urlsplit(purl).path.rstrip("/") == want.rstrip("/") or (
                        want == "/" and urllib.parse.urlsplit(purl).path in ("", "/")):
                    pages.append((fname, st, en))
                    break
            else:
                pages.append((fname, 1, len(lines) + 1))
        else:
            pages.append((fname, 1, len(lines) + 1))
    dedup = []
    for p in pages:
        if p not in dedup:
            dedup.append(p)
    return dedup


def dated_lines(claim, types, src_tree, idx, pages, words, strong=()):
    """`strong`: (path, line) pairs a source-grep check already hit; inside a dated block they rank first."""
    text = claim.get("claim", "")
    forms, years = claim_dates(text)
    cands = {}   # (path, line) -> (rank, tag); lower rank first; the cap keeps the best-matching lines
    for path, ln, rank in strong:
        if path in idx:
            g = governing_date(idx[path], ln)
            if g and g[0] != ln and (path, ln) not in cands:
                cands[(path, ln)] = (rank, f" [dated {g[1]} at L{g[0]}]")

    def add(path, ln, rank, tag=""):
        key = (path, ln)
        if key not in cands or cands[key][0] > rank:
            cands[key] = (rank, tag)

    # exact dates anywhere in the sources
    if forms:
        for path in sorted(src_tree):
            for i, line in enumerate(src_tree[path]):
                if any(f in line for f in forms):
                    add(path, i + 1, 0)
    # same-year dated lines on the claim's own pages
    if years and pages:
        for fname, st, en in pages:
            for ln, dt in idx[fname]["dated"]:
                if st <= ln < en and any(y in dt for y in years):
                    add(fname, ln, 1)
    # status claims: lines inside dated blocks that carry claim words (the C-097 class); more words rank higher
    if claim.get("kind") == "status" or "date" in types:
        for path in sorted(src_tree):
            lines = src_tree[path]
            for i, line in enumerate(lines):
                low = line.lower()
                n = sum(1 for w in words if w in low)
                if not n:
                    continue
                g = governing_date(idx[path], i + 1)
                if g and g[0] != i + 1:
                    add(path, i + 1, 10 - min(n, 8), f" [dated {g[1]} at L{g[0]}]")
    ordered = sorted(cands.items(), key=lambda kv: (kv[1][0], kv[0][0], kv[0][1]))[:MAX_DATED]
    out = []
    for (path, ln), (_rank, tag) in sorted(ordered, key=lambda kv: (kv[0][0], kv[0][1])):
        line = src_tree[path][ln - 1].strip()
        out.append(f"sources/{path}#L{ln}{tag}: {line[:240]}")
    return out


def parse_number(tok: str):
    t = tok.replace("$", "").replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def numbers_check(claim, pages, src_tree):
    text = claim.get("claim", "")
    percents = [(m.group(0).strip(), float(m.group(1))) for m in PERCENT_RE.finditer(text)]
    operands = []
    for m in NUMBER_RE.finditer(text):
        tok, unit = m.group(1), m.group(2)
        if unit == "%":
            continue
        tok = tok.rstrip(",.")
        val = parse_number(tok)
        if val is None:
            continue
        if re.fullmatch(r"(19|20)\d\d", tok):      # a year, not an operand
            continue
        operands.append((tok, val))
    if not percents and not operands:
        return []
    page_texts = []
    if pages:
        for fname, st, en in pages:
            page_texts.append((f"sources/{fname}#L{st}-L{en - 1}", "\n".join(src_tree[fname][st - 1:en - 1])))
    else:
        for fname in sorted(src_tree):
            for st, en, _ in page_sections(src_tree[fname]):
                page_texts.append((f"sources/{fname}#L{st}-L{en - 1}", "\n".join(src_tree[fname][st - 1:en - 1])))
    rows = []
    targets = percents or [(None, None)]
    for ptext, pval in targets:
        best = None
        for label, body in page_texts:
            found = [tok for tok, _ in operands if tok in body]
            if best is None or len(found) > len(best[1]):
                best = (label, found)
        found = best[1] if best else []
        row = {"text": ptext or ", ".join(t for t, _ in operands), "operands_found": found,
               "page": best[0] if best and found else None}
        vals = [v for t, v in operands if t in found]
        clean_shape = (len(percents) == 1 and len(operands) == 2
                       and claim.get("kind") in ("number", "comparison"))
        if pval is None or len(vals) < 2:
            row["arith"] = None
            row["status"] = "not-evaluable"
        elif not clean_shape:
            # several percentages or more than two figures: which pair belongs to which is a reading, not a sum
            row["arith"] = "ambiguous operands; not evaluated"
            row["status"] = "not-evaluable"
        else:
            a, b = sorted(vals[:2], reverse=True)
            # the operator comes from the claim's wording, never from whichever formula fits best
            low = text.lower()
            if re.search(r"\b(less|fewer|cheaper|lower|reduc\w*|drop\w*|fell|down|sav\w+|cut)\b", low) and a:
                expr, val = f"1-{b:g}/{a:g}", (1 - b / a) * 100
            elif re.search(r"\b(more|higher|increas\w*|grew|growth|up|faster|gain\w*)\b", low) and b:
                expr, val = f"{a:g}/{b:g}-1", (a / b - 1) * 100
            elif re.search(r"\b(of|out of|share|portion|rate)\b", low) and a:
                expr, val = f"{b:g}/{a:g}", b / a * 100
            else:
                expr, val = None, None
            if expr is None:
                row["arith"] = (f"no operator in the wording; candidates 1-{b:g}/{a:g}={(1 - b / a) if a else 0:.3f} "
                                f"{b:g}/{a:g}={(b / a) if a else 0:.3f} {a:g}/{b:g}-1={(a / b - 1) if b else 0:.3f}")
                row["status"] = "not-evaluable"
            else:
                decimals = len(ptext.split("%")[0].split(".")[1]) if "." in ptext.split("%")[0] else 0
                unit = 10 ** (-decimals)
                diff = abs(val - pval)
                rel = diff / pval if pval else diff
                row["arith"] = f"{expr}={val / 100:.3f}"
                row["status"] = "consistent" if (diff < unit or rel <= 0.01) else "inconsistent"
        rows.append(row)
    return rows


# ----------------------------------------------------------------------------------------------- the row

def build_row(claim, ctx):
    text = claim.get("claim", "")
    types, toks, urls = detect_types(claim)
    checks = []
    pages = claim_pages(claim, ctx["smap"], ctx["src"])
    words = content_words(text)
    queries = []
    for kind, tok in toks:
        if kind in ("backtick", "quoted"):
            queries.append(tok)
        elif kind in ("hyphen", "snake"):
            m = re.search(re.escape(tok) + r" ([a-z]+)", text)
            if m and m.group(1).lower() not in STOPWORDS:
                queries.append(f"{tok} {m.group(1)}")
            queries.append(tok)
            if kind == "hyphen":
                queries.append(tok.replace("-", "_"))
        else:
            queries.append(tok)
    dedup = []
    for q in queries:
        if q not in dedup:
            dedup.append(q)
    queries = dedup[:MAX_QUERIES]
    repo_queries = [q for q in queries if not re.fullmatch(r"[\d. %$]+", q)]
    for q in repo_queries:
        checks.append(check_repo_grep(ctx["repo"], q))
    for q in queries:
        checks.append(check_source_grep(ctx["src"], q))
    if not queries:
        for w in sorted(words, key=len, reverse=True)[:3]:
            checks.append(check_source_grep(ctx["src"], w))
    if "policy" in types:
        # the quantifier phrases ("every anchor", "only when") are where a policy claim and its sources disagree
        phrases = []
        for m in QUANTIFIER_RE.finditer(URL_RE.sub(" ", text)):
            ph = f"{m.group(1).lower()} {m.group(2).lower()}"
            if ph not in phrases and m.group(2).lower() not in ("one", "more", "the", "and", "for", "with"):
                phrases.append(ph)
        for ph in phrases[:4]:
            checks.append(check_source_grep(ctx["src"], ph))
    # the opposite wording, from the table (fires on its trigger words whatever the claim's type)
    low = text.lower()
    done = set()
    for trigger, opposites in OPPOSITES.items():
        if re.search(r"(?<![\w-])" + re.escape(trigger) + r"(?![\w-])", low):
            for op in opposites:
                if op not in done and op not in low:
                    done.add(op)
                    row = check_source_grep(ctx["src"], op)
                    row["role"] = "opposite"
                    checks.append(row)
    # every source the claim cites: GET it live and compare with the saved copy (drift since the lister ran)
    if ctx["http"] is not None:
        seen_urls = set()
        for s in claim.get("sources", []):
            su = (s.get("url") or "").rstrip("/")
            if not su or su in seen_urls:
                continue
            seen_urls.add(su)
            row = ctx["http"].get(su)
            row["role"] = "source"
            saved = SAVED_SHA.get(su)
            if saved and row.get("sha256"):
                row["saved_sha256"] = saved
                row["changed_since_saved"] = row["sha256"] != saved
            checks.append(row)
    if "url" in types:
        for u in resolve_urls(text, urls, ctx["hosts"]):
            if isinstance(u, tuple):
                checks.append({"check": "http-get", "url": u[1], "status": f"error:{u[0]}"})
            else:
                checks.append(ctx["http"].get(u))
    if "licence" in types:
        checks.append(check_repo_files(ctx["repo"], LICENCE_FILE, "LICENSE*"))
        for w in ("MIT", "Apache", "GPL", "licence", "license"):
            if re.search(r"\b" + w, text, re.I):
                checks.append(check_source_grep(ctx["src"], w))
    if "repo-metadata" in types:
        checks.append(check_metadata(ctx["run_dir"]))
    if "version" in types:
        versions = sorted({t for k, t in toks if k == "version"})
        for v in versions:
            checks.append(check_repo_grep(ctx["repo"], v))
        seen = {}
        for path in sorted(ctx["src"]):
            for line in ctx["src"][path]:
                for v in re.findall(r"\bv?\d+\.\d+\.\d+\b", line):
                    seen.setdefault(path, set()).add(v.lstrip("v"))
        checks.append({"check": "versions-seen", "query": ",".join(versions),
                       "per_source": {p: sorted(s) for p, s in seen.items()}, "status": "found" if seen else "not-found"})
    row = {"id": claim["id"], "types": types, "checks": checks}
    strong = []   # opposite-wording hits rank 2, other source-grep hits rank 3, inside a dated block
    for c in sorted(checks, key=lambda c: 0 if c.get("role") == "opposite" else 1):
        if c["check"] == "source-grep":
            for h in c.get("hits", []):
                m = re.fullmatch(r"sources/(.+)#L(\d+)", h)
                if m:
                    strong.append((m.group(1), int(m.group(2)), 2 if c.get("role") == "opposite" else 3))
    dl = dated_lines(claim, types, ctx["src"], ctx["idx"], pages, words, strong)
    if dl:
        row["dated_lines"] = dl
    if "number" in types:
        nums = numbers_check(claim, pages, ctx["src"])
        if nums:
            row["numbers"] = nums
    if "policy" in types:
        row["negative"] = True
    return row


# ----------------------------------------------------------------------------------------------- commands

def run_check(run_dir, offline=False, fetch=None):
    claims = read_jsonl(os.path.join(run_dir, "claims.jsonl"))
    run = load_run(run_dir)
    SAVED_SHA.clear()
    src = load_tree(os.path.join(run_dir, "sources"))
    repo_dir = os.path.join(run_dir, "repo")
    repo = load_tree(repo_dir) if os.path.isdir(repo_dir) else None
    http = HttpClient(run_dir, run.get("hosts", []), offline=offline, fetch=fetch, connector_hosts=run.get("connector_hosts", []))
    ctx = {"run_dir": run_dir, "src": src, "repo": repo, "idx": date_index(src), "smap": source_map(run_dir),
           "hosts": run.get("hosts", []), "http": http}
    rows = [build_row(c, ctx) for c in claims]
    out = os.path.join(run_dir, "checks.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    http.save()
    summary = write_summary(run_dir, rows, run, repo is not None, http)
    return out, rows, summary


def write_summary(run_dir, rows, run, repo_present, http):
    from collections import Counter
    by_check = {}
    for r in rows:
        for c in r["checks"]:
            by_check.setdefault(c["check"], Counter())[str(c["status"])] += 1
    lines = [f"# checks-summary ({run.get('publisher', '')} {run.get('domain', '')})", "",
             f"rows: {len(rows)}  ·  repo/: {'present at ' + run.get('repo_commit', '?') if repo_present else 'ABSENT: every repo-grep says no-repo'}",
             f"http: {len(http.cache)} distinct URLs cached, {http.requests_made} requests made this run"
             + (" (offline mode)" if http.offline else ""), ""]
    lines.append("| check | status | count |")
    lines.append("|---|---|---|")
    for chk in sorted(by_check):
        for st, n in sorted(by_check[chk].items()):
            lines.append(f"| {chk} | {st} | {n} |")
    refused = sorted({c["url"] for r in rows for c in r["checks"]
                      if c["check"] == "http-get" and c["status"] == "error:host-not-allowed"})
    if refused:
        lines += ["", "hosts refused (outside run.json.hosts): " + ", ".join(refused)]
    drift = sorted({c["url"] for r in rows for c in r["checks"] if c.get("changed_since_saved")})
    if drift:
        lines += ["", "sources changed since the lister saved them (live sha256 differs): " + ", ".join(drift)]
    nums = Counter(n["status"] for r in rows for n in r.get("numbers", []))
    lines += ["", f"numbers: {dict(sorted(nums.items()))}",
              f"dated_lines: {sum(len(r.get('dated_lines', [])) for r in rows)} quoted over "
              f"{sum(1 for r in rows if r.get('dated_lines'))} claims",
              f"negative (policy) claims: {sum(1 for r in rows if r.get('negative'))}"]
    types = Counter(t for r in rows for t in r["types"])
    lines += ["", "types: " + ", ".join(f"{t} {n}" for t, n in sorted(types.items()))]
    path = os.path.join(run_dir, "checks-summary.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def format_check_block(rows):
    parts = ["## Check results (claims-harness, mechanical, per claim)", "", GRADE_SENTENCE, ""]
    for r in rows:
        parts.append(f"### {r['id']}  types: {', '.join(r['types'])}" + ("  negative: true" if r.get("negative") else ""))
        for c in r["checks"]:
            if c["check"] in ("repo-grep", "source-grep"):
                extra = f" (+{c['total'] - len(c['hits'])} more)" if c.get("total") else ""
                role = " (opposite wording)" if c.get("role") == "opposite" else ""
                parts.append(f"- {c['check']}{role} `{c['query']}`: {c['status']} {' '.join(c['hits'])}{extra}")
            elif c["check"] == "http-get":
                tag = " (claim source)" if c.get("role") == "source" else ""
                drift = " CHANGED since the saved copy" if c.get("changed_since_saved") else ""
                parts.append(f"- http-get{tag} {c['url']}: {c['status']}"
                             + (f" sha256 {c['sha256'][:16]}…" if c.get("sha256") else "") + drift)
            elif c["check"] == "repo-metadata":
                parts.append(f"- repo-metadata: {c['status']} {json.dumps(c.get('fields', {}), sort_keys=True)}")
            elif c["check"] == "versions-seen":
                parts.append(f"- versions-seen: {json.dumps(c.get('per_source', {}), sort_keys=True)}")
            else:
                parts.append(f"- {c['check']} {c.get('query', '')}: {c['status']} {' | '.join(c.get('hits', []))}")
        for d in r.get("dated_lines", []):
            parts.append(f"- dated: {d}")
        for n in r.get("numbers", []):
            parts.append(f"- numbers {n['text']}: operands {n['operands_found']} on {n['page']} arith {n['arith']} → {n['status']}")
        parts.append("")
    return "\n".join(parts)


def run_prompt(kind, run_dir):
    if kind not in ("prove", "disprove"):
        raise SystemExit("prompt kind must be prove or disprove")
    with open(os.path.join(HERE, "prompts", f"{kind}.md"), encoding="utf-8") as f:
        base = f.read()
    run = load_run(run_dir)
    repo_dir = os.path.join(run_dir, "repo")
    extra = (f"- A read-only clone of the public repository at commit {run.get('repo_commit', '?')}: {run_dir}/repo "
             f"(read it, never build or run it).") if os.path.isdir(repo_dir) else ""
    base = (base.replace("{{PUBLISHER}}", run.get("publisher", "")).replace("{{DOMAIN}}", run.get("domain", ""))
            .replace("{{OUT}}", run_dir).replace("{{EXTRA_SOURCES}}", extra))
    rows = read_jsonl(os.path.join(run_dir, "checks.jsonl"))
    block = format_check_block(rows)
    out = os.path.join(run_dir, f"prompt-{kind}.md")
    if len(base) + len(block) + 2 > PROMPT_LIMIT:
        side = os.path.join(run_dir, "checks-for-prompt.md")
        with open(side, "w", encoding="utf-8") as f:
            f.write(block)
        text = (base + "\n\n## Check results\n\n" + GRADE_SENTENCE + f"\nThe per-claim check results are in {side} "
                "(one `### C-nnn` section per claim); read a claim's section before searching for it.\n")
    else:
        text = base + "\n\n" + block
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    return out


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "check":
        run_dir = os.path.abspath(argv[2])
        offline = "--offline" in argv[3:]
        out, rows, summary = run_check(run_dir, offline=offline)
        with open(out, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        print(f"{out}: {len(rows)} rows, sha256 {digest}")
        print(f"{summary}")
        return 0
    if cmd == "prompt":
        out = run_prompt(argv[2], os.path.abspath(argv[3]))
        print(f"{out}: {os.path.getsize(out)} chars")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
