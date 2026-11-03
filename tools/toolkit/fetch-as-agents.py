#!/usr/bin/env python3
"""Fetch each published page the way each AI app's fetcher would, and check it is the page a browser gets.

    python3 -I fetch-as-agents.py URL [URL ...] [--json out.json] [--md out.md] [--timeout 20]

Why: on 27 Oct 2026 onedroid.ai served a 38 KB text/markdown "twin" to every AI user-agent, so ChatGPT, Perplexity and
Copilot reported "unsupported content-type" / "no content" instead of reading the evidence pages. Nobody noticed because
every check used a browser. This tool sends one GET per URL and profile (user-agent plus Accept header), and compares
what comes back with what the browser profile got for the same URL.

Per (URL, profile) it records status, content-type (lowercased, before the first semicolon), bytes, elapsed ms and, for
text/html, a plain-text extract (script/style dropped, tags stripped, entities unescaped, whitespace collapsed), its
length, the <title> and the sorted unique claim anchors matched by id="(C-\\d+)".

Verdict, relative to the browser profile for the same URL:
  SAME       same content-type as the browser, same anchor set, extract length >= 90% of the browser's
  TWIN       content-type text/markdown. PASS only for control profiles, FAIL for every other profile
  DIFFERENT  text/html (or other) but the content-type, the anchor set or the length rule differs
  ERROR      non-200 status or an exception (message recorded)
Exit code 0 when every non-control profile is SAME on every URL, else 1. Controls never change the exit code.
Stdlib only. The pure parts (extract_text, claim_anchors, verdict) are separate from the one effect, fetch().
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request

# Header strings are verbatim. control=True marks profiles whose different answer is expected, not a failure.
PROFILES = [
    {"name": "browser", "control": False,
     "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
     "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"},
    # This exact UA/Accept pair was captured from the real fetcher via httpbin by PostHog,
    # github.com/PostHog/posthog.com issue #21381, 2026-10-19.
    {"name": "chatgpt-user", "control": False,
     "user_agent": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot",
     "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
    {"name": "gptbot", "control": False,
     "user_agent": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.2; +https://openai.com/gptbot",
     "accept": "*/*"},
    {"name": "perplexity-user", "control": False,
     "user_agent": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user)",
     "accept": "*/*"},
    {"name": "perplexitybot", "control": False,
     "user_agent": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)",
     "accept": "*/*"},
    {"name": "claude-user", "control": False,
     "user_agent": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; +Claude-User@anthropic.com)",
     "accept": "*/*"},
    {"name": "claudebot", "control": False,
     "user_agent": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)",
     "accept": "*/*"},
    # Expected to get the markdown twin on onedroid.ai: a control, not a failure.
    {"name": "claude-code-webfetch", "control": True,
     "user_agent": "Mozilla/5.0 (compatible; Claude-Code/1.0)",
     "accept": "text/markdown, */*"},
    {"name": "google-extended", "control": False,
     "user_agent": "Mozilla/5.0 (compatible; Google-Extended/1.0; +https://developers.google.com/search/docs/crawling-indexing/overview-google-crawlers)",
     "accept": "*/*"},
    {"name": "bingbot", "control": False,
     "user_agent": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm) Chrome/116.0.1938.76 Safari/537.36",
     "accept": "*/*"},
    {"name": "no-accept-header", "control": False, "user_agent": "ChatGPT-User/1.0", "accept": None},
    {"name": "accept-markdown", "control": True, "user_agent": "ChatGPT-User/1.0", "accept": "text/markdown"},
]

LENGTH_NUM, LENGTH_DEN = 9, 10  # extract length must be >= 90% of the browser's

_BLOCKS = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_TAGS = re.compile(r"<[^>]*>")
_TITLE = re.compile(r"<title\b[^>]*>(.*?)</title\s*>", re.I | re.S)
_ANCHOR = re.compile(r'id="(C-\d+)"')


def extract_text(body):
    """Plain text of an HTML body: script/style blocks dropped, tags stripped, entities unescaped, whitespace collapsed."""
    text = _TAGS.sub(" ", _BLOCKS.sub(" ", body))
    return " ".join(html.unescape(text).split())


def claim_anchors(body):
    """Sorted unique claim anchors (id="C-<n>") in the body."""
    return sorted(set(_ANCHOR.findall(body)))


def title_of(body):
    m = _TITLE.search(body)
    return " ".join(html.unescape(m.group(1)).split()) if m else ""


def verdict(rec, base):
    """SAME | TWIN | DIFFERENT | ERROR for a record against the browser record of the same URL (pure)."""
    if rec.get("error") or rec.get("status") != 200:
        return "ERROR"
    if rec.get("content_type") == "text/markdown":
        return "TWIN"
    if not base or base.get("error") or base.get("status") != 200:
        return "ERROR"
    if rec.get("content_type") != base.get("content_type"):
        return "DIFFERENT"
    if rec.get("anchors") != base.get("anchors"):
        return "DIFFERENT"
    if rec.get("extract_chars", 0) * LENGTH_DEN < base.get("extract_chars", 0) * LENGTH_NUM:
        return "DIFFERENT"
    return "SAME"


def passes(v, control):
    """Acceptable for this profile: SAME always, anything for a control (TWIN is the expected control answer)."""
    return True if control else v == "SAME"


def fetch(url, profile, timeout=20):
    """The one effect: one GET with the profile's headers. Returns a record dict, never raises."""
    headers = {"User-Agent": profile["user_agent"]}
    if profile.get("accept") is not None:
        headers["Accept"] = profile["accept"]
    rec = {"url": url, "profile": profile["name"], "control": profile["control"], "final_url": url, "status": None,
           "content_type": None, "bytes": 0, "elapsed_ms": 0, "extract_chars": 0, "title": "", "anchors": [],
           "error": None}
    t0 = time.monotonic()
    data = b""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
            data = r.read()
            rec["status"] = r.status
            rec["final_url"] = r.geturl()
            rec["content_type"] = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    except urllib.error.HTTPError as e:
        rec["status"] = e.code
        rec["error"] = "HTTP %s" % e.code
        rec["content_type"] = (e.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    except Exception as e:  # record any failure, do not raise
        rec["error"] = "%s: %s" % (type(e).__name__, e)
    rec["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    rec["bytes"] = len(data)
    if rec["content_type"] == "text/html" and not rec["error"]:
        body = data.decode("utf-8", "replace")
        rec["extract_chars"] = len(extract_text(body))
        rec["title"] = title_of(body)
        rec["anchors"] = claim_anchors(body)
    return rec


def run(urls, timeout):
    records = []
    for url in urls:
        base = None
        for p in PROFILES:
            rec = fetch(url, p, timeout)
            if p["name"] == "browser":
                base = rec
            rec["verdict"] = verdict(rec, base)
            rec["ok"] = passes(rec["verdict"], p["control"])
            records.append(rec)
    return records


HEAD = ["url", "profile", "status", "content-type", "bytes", "extract chars", "anchors", "verdict"]


def rows(records):
    for r in records:
        v = r["verdict"] + ("" if r["ok"] else " FAIL")
        if r["error"] and r["status"] is None:
            v += " " + r["error"]
        yield [r["url"], r["profile"] + (" (control)" if r["control"] else ""), str(r["status"] or "-"),
               r["content_type"] or "-", str(r["bytes"]), str(r["extract_chars"]), str(len(r["anchors"])), v]


def summary(records):
    bad = [r for r in records if not r["ok"]]
    names = ", ".join("%s=%s" % (r["profile"], r["verdict"]) for r in bad) or "none"
    return "%d fetches, %d non-control failures: %s" % (len(records), len(bad), names)


def table(records):
    data = [HEAD] + list(rows(records))
    w = [max(len(row[i]) for row in data) for i in range(len(HEAD))]
    return "\n".join("  ".join(c.ljust(w[i]) for i, c in enumerate(row)).rstrip() for row in data)


def markdown(records):
    out = ["| " + " | ".join(HEAD) + " |", "|" + "---|" * len(HEAD)]
    out += ["| " + " | ".join(c.replace("|", "\\|") for c in row) + " |" for row in rows(records)]
    return "\n".join(out) + "\n\n" + summary(records) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--json")
    ap.add_argument("--md")
    ap.add_argument("--timeout", type=float, default=20)
    a = ap.parse_args(argv)
    records = run(a.urls, a.timeout)
    print(table(records))
    print(summary(records))
    if a.json:
        with open(a.json, "w") as f:
            json.dump(records, f, indent=2)
    if a.md:
        with open(a.md, "w") as f:
            f.write(markdown(records))
    return 0 if all(r["ok"] for r in records) else 1


if __name__ == "__main__":
    sys.exit(main())
