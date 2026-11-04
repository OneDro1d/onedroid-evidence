#!/usr/bin/env python3
"""Generate llms-full.txt from the site's HTML.

SITE-11 (CMO#16) shipped /llms.txt to spec. The other half of that finding asked for
a Markdown twin of every page. Those were DECLINED: the site is hand-written HTML with
no generator, so twins would have nothing to be derived from — and a twin is what an
agent reads while humans read the HTML, so a stale twin serves wrong content to exactly
its audience with no feedback loop.

llms-full.txt is the part worth having: one concatenated document, and — unlike a twin —
DERIVED, so it cannot silently drift.

    python3 tools/gen-llms-full.py            # regenerate llms-full.txt
    python3 tools/gen-llms-full.py --check    # exit 1 if llms-full.txt is stale

Run --check before a deploy. Stdlib only, on purpose: this repo has no build step and
no package manifest, and a generator that needs `pip install` is one that stops getting
run. See MAP.md, "SITE-11 — open decision", for the reasoning that produced this shape.
"""

import html
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "llms-full.txt"

# Ordered to match the reading order an agent should take: what it is, how to connect,
# what it costs, then the legal surface. Mirrors the section order of llms.txt.
PAGES = [
    ("index.html", "/"),
    ("argus.html", "/argus"),
    ("case-studies.html", "/case-studies"),
    ("case-study-otrs-znuny.html", "/case-study-otrs-znuny"),
    ("case-study-finos-calm.html", "/case-study-finos-calm"),
    ("case-study-claude-code-alone-vs-tester.html", "/case-study-claude-code-alone-vs-tester"),
    ("case-study-modernization-three-setups.html", "/case-study-modernization-three-setups"),
    ("synapse.html", "/synapse"),
    ("what-is-a-governed-mcp-gateway.html", "/what-is-a-governed-mcp-gateway"),
    ("quickstart.html", "/quickstart"),
    # /docs moved to its own site on 2026-08-21 — docs.onedroid.ai, built from the public
    # repo OneDro1d/onedroid-docs. Deliberately NOT listed here: it is a different origin
    # with its own llms.txt and sitemap, and mirroring it back into this file would
    # recreate the second copy the move existed to remove. /docs now 308s there.
    ("security.html", "/security"),
    ("engram.html", "/engram"),
    ("financial-services.html", "/financial-services"),
    ("qa-teams.html", "/qa-teams"),
    ("dark-factory.html", "/dark-factory"),
    ("kit.html", "/kit"),
    ("enterprise.html", "/enterprise"),
    ("pricing.html", "/pricing"),
    ("about.html", "/about"),
    ("changelog.html", "/changelog"),
    ("contact.html", "/contact"),
    ("privacy.html", "/privacy"),
    ("terms.html", "/terms"),
    # Evidence pages (2026-10-27): third-party records of what a company's own site claims and
    # what backs it. Generated from an audit run by the notepad's gen-evidence-page.py; the HTML
    # is the artefact, twins derive from it like every other page.
    ("evidence/index.html", "/evidence"),
    ("evidence/onedroid.ai.html", "/evidence/onedroid.ai"),
    ("evidence/mcmahonconstruction.ie.html", "/evidence/mcmahonconstruction.ie"),
    ("evidence/ormondeconstruction.ie.html", "/evidence/ormondeconstruction.ie"),
]

HEADER = """# OneDroid — full site text for language models

This file is GENERATED from the HTML pages of https://onedroid.ai by
tools/gen-llms-full.py. The HTML pages are authoritative; if this file and a page
disagree, the page is correct and this file is stale — regenerate it.

Index and connection details: https://onedroid.ai/llms.txt

OneDroid (onedroid.ai) builds AI agent infrastructure. It is unrelated to Android and to
the open-source Android projects also called "OneDroid".

"""

BLOCK = {"p", "div", "section", "article", "li", "tr", "blockquote", "pre",
         "h1", "h2", "h3", "h4", "h5", "h6"}
DROP = {"script", "style", "nav", "header", "footer", "svg", "noscript", "template"}
HEADINGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}


class MainExtractor(HTMLParser):
    """Collect text from <main>, preserving heading level and list structure."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth_main = 0
        self.drop_depth = 0
        self.parts = []
        self.heading = None
        self.in_li = False
        self.in_code = False

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.depth_main += 1
            return
        if not self.depth_main:
            return
        if tag in DROP:
            self.drop_depth += 1
            return
        if self.drop_depth:
            return
        if tag in HEADINGS:
            self.parts.append("\n\n" + HEADINGS[tag] + " ")
            self.heading = tag
        elif tag == "li":
            self.parts.append("\n- ")
            self.in_li = True
        elif tag in ("code", "kbd"):
            self.in_code = True
            self.parts.append("`")
        elif tag == "br":
            self.parts.append("\n")
        elif tag in BLOCK:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag == "main":
            self.depth_main = max(0, self.depth_main - 1)
            return
        if not self.depth_main:
            return
        if tag in DROP:
            self.drop_depth = max(0, self.drop_depth - 1)
            return
        if self.drop_depth:
            return
        if tag in HEADINGS:
            self.heading = None
            self.parts.append("\n")
        elif tag == "li":
            self.in_li = False
        elif tag in ("code", "kbd"):
            self.in_code = False
            self.parts.append("`")
        elif tag in ("td", "th"):
            # Without a separator the cells of a row run together ("ItemValue").
            self.parts.append(" | ")
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.depth_main and not self.drop_depth:
            self.parts.append(data)

    def text(self):
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r" *\n *", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        # An empty inline code span is an artefact of tag stripping, not content.
        raw = raw.replace("``", "")
        return raw.strip()


def meta(source, prop, attr="name"):
    # The closing quote must be the SAME character that opened the attribute: a
    # non-greedy (.*?)["\'] stopped at the apostrophe in "says it's done" and
    # silently truncated the home description to 25 characters (found by LA-3 QA,
    # 2026-09-10). A backreference makes the capture end at the real delimiter.
    m = re.search(
        r'<meta\s+%s=["\']%s["\']\s+content=(["\'])(.*?)\1' % (attr, re.escape(prop)),
        source, re.I | re.S)
    return html.unescape(m.group(2)).strip() if m else ""


def title(source):
    m = re.search(r"<title>(.*?)</title>", source, re.I | re.S)
    return html.unescape(m.group(1)).strip() if m else ""


def render():
    out = [HEADER]
    for filename, url in PAGES:
        if url.startswith("/evidence"):
            # Third-party evidence pages (what another company's site claims) are not OneDroid
            # full site text; OneDroid's own claims page /evidence/onedroid.ai is, and is
            # included. The index is /evidence and llms.txt points there.
            continue
        path = ROOT / filename
        if not path.exists():
            sys.stderr.write("MISSING: %s (listed in PAGES)\n" % filename)
            sys.exit(2)
        source = path.read_text(encoding="utf-8")
        parser = MainExtractor()
        parser.feed(source)
        body = parser.text()
        if not body:
            sys.stderr.write("EMPTY <main>: %s — refusing to emit a hollow section\n" % filename)
            sys.exit(2)
        out.append("\n\n%s\n\n" % ("=" * 76))
        out.append("# PAGE: https://onedroid.ai%s\n" % url)
        out.append("Title: %s\n" % title(source))
        desc = meta(source, "description")
        if desc:
            out.append("Description: %s\n" % desc)
        out.append("\n%s\n" % body)
    return "".join(out).rstrip() + "\n"


def main():
    generated = render()
    if "--check" in sys.argv:
        if not OUT.exists():
            sys.stderr.write("STALE: llms-full.txt does not exist. Run without --check.\n")
            return 1
        if OUT.read_text(encoding="utf-8") != generated:
            sys.stderr.write(
                "STALE: llms-full.txt does not match the HTML. Run:\n"
                "  python3 tools/gen-llms-full.py\n")
            return 1
        sys.stdout.write("OK: llms-full.txt matches the HTML (%d pages, %d chars).\n"
                         % (len(PAGES), len(generated)))
        return 0
    OUT.write_text(generated, encoding="utf-8")
    sys.stdout.write("Wrote %s (%d pages, %d chars).\n" % (OUT.name, len(PAGES), len(generated)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
