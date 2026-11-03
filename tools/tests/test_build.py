"""Tests for tools/build.py: the evidence site compiler and its CI invariants I-1, I-2, I-4, I-8
(argus-claims docs/dark-factory/02-sa-service-map §5, 02-sa-data-model §6; VR-09, VR-11, R-09.3; scenario S-05)."""
import contextlib
import hashlib
import importlib.util
import io
import json
import pathlib
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

TOOLS = pathlib.Path(__file__).resolve().parent.parent
REPO = TOOLS.parent
GOLDEN = TOOLS / "tests" / "goldens" / "live-2026-11-02"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _load("build", TOOLS / "build.py")
IMPORT = _load("import_run", TOOLS / "toolkit" / "import_run.py")

# The only failure the real repo may show: a toolkit vendored from an uncommitted argus-claims tree (I-9), which is
# right until argus-claims is committed and the toolkit re-vendored from that commit.
_PIN = (TOOLS / "toolkit" / "TOOLKIT_VERSION").read_text(encoding="utf-8").split()[0]
REPO_FAILURES = [f"I-9 tools/toolkit/TOOLKIT_VERSION: {_PIN} vendored from an uncommitted argus-claims tree"] if _PIN.endswith("+local") else []

def clean_kit(dest):
    """A copy of the vendored toolkit pinned to a committed-looking id, for fixture trees: their checks are about the
    fixture, not about whether argus-claims is committed yet (the real pin is tested on the real repo)."""
    shutil.copytree(B.KIT, dest, ignore=shutil.ignore_patterns("__pycache__"))
    sha = hashlib.sha256((dest / "MANIFEST").read_bytes()).hexdigest()
    (dest / "TOOLKIT_VERSION").write_text(f"0123abc {sha}\n", encoding="utf-8")
    return dest


THIRD_PARTY = (("mcmahonconstruction.ie", "McMahon Construction", "r-20261027T190540Z-imp", 47, 1, 0, 46),
               ("ormondeconstruction.ie", "Ormonde Construction Ltd", "r-20261027T190529Z-imp", 75, 5, 3, 67))

PAGE = b"<html><body>We build houses. Est. 1990.</body></html>"
SHA = hashlib.sha256(PAGE).hexdigest()


def jsonl(rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


def add_to_manifest(run, rel, data):
    """Put a file in a run folder and list it in manifest.sha256, sorted, as the importer would."""
    (run / rel).parent.mkdir(parents=True, exist_ok=True)
    (run / rel).write_bytes(data)
    lines = (run / "manifest.sha256").read_text(encoding="utf-8").splitlines()
    lines.append(f"{hashlib.sha256(data).hexdigest()}  {rel}")
    (run / "manifest.sha256").write_text("".join(l + "\n" for l in sorted(lines, key=lambda l: l.split("  ", 1)[1])),
                                         encoding="utf-8")


def make_domain(root, domain="x.example", texts=("We build houses.", "Established in 1990.", "We are the best."),
                front=None, changelog="2026-10-30: first run.\n", low=False):
    """A small evidence-repo domain: one imported run with one evidenced, one contradicted, one no-evidence claim."""
    root = pathlib.Path(root)
    src = root.parent / f"src-{domain}"
    (src / "sources").mkdir(parents=True)
    (src / "sources" / "a.html").write_bytes(PAGE)
    (src / "claims.md").write_text("| source URL | local file | HTTP | bytes | sha256 |\n|---|---|---|---|---|\n"
                                   f"| https://{domain}/ | sources/a.html | 200 | {len(PAGE)} | {SHA} |\n", encoding="utf-8")
    ids = [f"C-00{i}" for i in range(1, len(texts) + 1)]
    (src / "claims.jsonl").write_text(jsonl([{"id": i, "claim": t, "kind": "capability", "checkability": "A",
                                              "sources": [{"url": f"https://{domain}/", "locator": "body"}]}
                                             for i, t in zip(ids, texts)]), encoding="utf-8")
    prove = [{"id": i, "evidence": "artefact" if n == 0 else "none",
              "refs": [{"ref": "sources/a.html#L1", "quote": "We build houses."}] if n == 0 else [], "note": "n"}
             for n, i in enumerate(ids)]
    disprove = [{"id": i, "contradiction": "yes" if n == 1 else "no", "confidence": "high",
                 "sides": [{"ref": "sources/a.html#L1", "quote": "Est. 1990."}, {"ref": f"https://{domain}/about", "quote": "since 1995"}],
                 "refs": [], "note": "low confidence: the two dates differ" if low else "the two dates differ"} if n == 1 else
                {"id": i, "contradiction": "no", "refs": [], "note": "no conflict"} for n, i in enumerate(ids)]
    (src / "prove.jsonl").write_text(jsonl(prove), encoding="utf-8")
    (src / "disprove.jsonl").write_text(jsonl(disprove), encoding="utf-8")
    (src / "run.json").write_text(json.dumps({"fetched_at": "2026-10-30T10:00:00Z", "hosts": [domain]}), encoding="utf-8")
    IMPORT.import_run(src, root / domain / "runs" / "r-1", domain, "X Ltd", "r-1")
    (root / domain / "index.md").write_text(front if front is not None else
                                            "---\npublisher: X Ltd\ncurrent_run: r-1\nself: false\nsplit_low_confidence: false\n---\n",
                                            encoding="utf-8")
    if changelog is not None:
        (root / domain / "changelog.md").write_text(changelog, encoding="utf-8")
    config = root / "config" / "exclusions.json"  # I-9: one entry per domain, = its current run's exclusions
    config.parent.mkdir(exist_ok=True)
    rules = json.loads(config.read_text(encoding="utf-8")) if config.exists() else {}
    config.write_text(json.dumps({**rules, domain: []}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return root / domain


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.out = pathlib.Path(self.tmp.name) / "dist"
        self.kit_patch = mock.patch.object(B, "KIT", clean_kit(pathlib.Path(self.tmp.name) / "kit"))
        self.kit_patch.start()

    def tearDown(self):
        self.kit_patch.stop()
        self.tmp.cleanup()

    def failures(self, invariant):
        return [f for f in B.check(self.root) if f.startswith(invariant + " ")]


class FrontMatter(Fixture):
    def write(self, text):
        path = self.root / "index.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_reads_the_keys_and_bools(self):
        meta = B.front_matter(self.write("---\npublisher: A & B Ltd\ncurrent_run: r-1\nself: true\n"
                                         "split_low_confidence: false\ncertificate_url: https://x/c\ncertificate_note: Seen.\n---\nbody\n"))
        self.assertEqual(meta, {"publisher": "A & B Ltd", "current_run": "r-1", "self": True, "split_low_confidence": False,
                                "certificate_url": "https://x/c", "certificate_note": "Seen."})

    def test_defaults(self):
        self.assertEqual(B.front_matter(self.write("---\npublisher: A\ncurrent_run: r-1\n---\n")),
                         {"publisher": "A", "current_run": "r-1", "self": False, "split_low_confidence": False,
                          "certificate_url": None, "certificate_note": None})

    def test_refusals_name_the_file(self):
        for text in ("publisher: A\ncurrent_run: r-1\n",                                  # no fences
                     "---\ncurrent_run: r-1\n---\n",                                       # no publisher
                     "---\npublisher: A\n---\n",                                           # no current_run
                     "---\npublisher: A\ncurrent_run: r-1\ncolour: red\n---\n",            # unknown key
                     "---\npublisher: A\npublisher: B\ncurrent_run: r-1\n---\n",           # repeated key
                     "---\npublisher: A\ncurrent_run: r-1\nself: yes\n---\n",              # not a bool
                     "---\npublisher: A\ncurrent_run: r-1\ncertificate_note: n\n---\n",    # note without url
                     "---\npublisher: A\ncurrent_run: r-1\njust words\n---\n",             # not key: value
                     "---\npublisher: A\ncurrent_run: ../../x\n---\n"):                    # not a run id
            with self.subTest(text=text):
                with self.assertRaisesRegex(B.BuildError, "index.md"):
                    B.front_matter(self.write(text))

    def test_a_current_run_with_no_folder_fails_the_build(self):
        make_domain(self.root, front="---\npublisher: X Ltd\ncurrent_run: r-9\n---\n")
        with self.assertRaisesRegex(B.BuildError, "r-9"):
            B.build(self.root, self.out)

    def test_a_domain_folder_without_index_fails_the_build(self):
        make_domain(self.root)
        (self.root / "x.example" / "index.md").unlink()
        with self.assertRaisesRegex(B.BuildError, "x.example"):
            B.build(self.root, self.out)


class ThirdPartyPages(unittest.TestCase):
    """The repo's own McMahon and Ormonde folders compile to the pages live on onedroid.ai today, byte for byte."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = pathlib.Path(cls.tmp.name) / "dist"
        cls.log = B.build(REPO, cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_html_equals_the_live_page(self):
        for domain, *_ in THIRD_PARTY:
            with self.subTest(domain=domain):
                self.assertEqual((self.out / "evidence" / f"{domain}.html").read_bytes(), (GOLDEN / f"{domain}.html").read_bytes())

    def test_markdown_twin_equals_the_live_twin(self):
        for domain, *_ in THIRD_PARTY:
            with self.subTest(domain=domain):
                self.assertEqual((self.out / "evidence" / f"{domain}.md").read_bytes(), (GOLDEN / f"{domain}.md").read_bytes())

    def test_jsonl_is_the_register_byte_for_byte(self):
        for domain, _p, run_id, *_ in THIRD_PARTY:
            with self.subTest(domain=domain):
                self.assertEqual((self.out / "evidence" / f"{domain}.jsonl").read_bytes(),
                                 (REPO / domain / "runs" / run_id / "register.jsonl").read_bytes())

    def test_json_twin(self):
        for domain, publisher, run_id, total, ev, co, ne in THIRD_PARTY:
            with self.subTest(domain=domain):
                page = json.loads((self.out / "evidence" / f"{domain}.json").read_text(encoding="utf-8"))
                register = [json.loads(x) for x in (REPO / domain / "runs" / run_id / "register.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual(list(page), ["schema", "domain", "publisher", "run_id", "checked", "counts", "claims", "sources"])
                self.assertEqual((page["schema"], page["domain"], page["publisher"], page["run_id"], page["checked"]),
                                 ("argus-claims/evidence-page@1", domain, publisher, run_id, "2026-10-27"))
                self.assertEqual(page["counts"], {"total": total, "evidenced": ev, "contradicted": co,
                                                  "low_confidence": sum(r.get("confidence") == "low" for r in register),
                                                  "no_evidence_published": ne, "evidence_private": 0})
                self.assertEqual(page["claims"], register)
                table = [l for l in (REPO / domain / "runs" / run_id / "claims.md").read_text(encoding="utf-8").splitlines()
                         if l.startswith("| https://")]
                self.assertEqual(len(page["sources"]), len(table))
                self.assertEqual([s["url"] for s in page["sources"]], [l.split("|")[1].strip() for l in table])
                self.assertEqual([s["sha256"] for s in page["sources"]], [l.split("|")[5].strip() for l in table])

    def test_every_run_record_is_downloadable_byte_for_byte(self):
        for domain, _p, run_id, *_ in THIRD_PARTY:
            src = REPO / domain / "runs" / run_id
            dst = self.out / "evidence" / domain / "runs" / run_id
            with self.subTest(domain=domain):
                self.assertEqual(sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file()),
                                 sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file()))
                for p in src.rglob("*"):
                    if p.is_file():
                        self.assertEqual((dst / p.relative_to(src)).read_bytes(), p.read_bytes())

    def test_the_build_log_names_what_it_wrote(self):
        self.assertTrue(any("evidence/mcmahonconstruction.ie.html" in line for line in self.log))

    def test_the_repo_passes_its_own_check(self):
        self.assertEqual(B.check(REPO), REPO_FAILURES)


class Building(Fixture):
    def test_refuses_a_non_empty_output_folder(self):
        make_domain(self.root)
        self.out.mkdir()
        (self.out / "old.html").write_text("x", encoding="utf-8")
        with self.assertRaises(B.BuildError):
            B.build(self.root, self.out)

    def test_refuses_a_symlink_in_a_domain_folder(self):
        outside = pathlib.Path(self.tmp.name) / "outside.txt"
        outside.write_text("not for the site", encoding="utf-8")
        for place in ("runs/r-1/extra.txt", "changelog.md"):
            with self.subTest(place=place):
                domain = make_domain(self.root)
                (domain / place).unlink(missing_ok=True)
                (domain / place).symlink_to(outside)
                with self.assertRaisesRegex(B.BuildError, place.rsplit("/", 1)[-1]):
                    B.build(self.root, self.out)
                shutil.rmtree(domain)
                shutil.rmtree(self.root.parent / "src-x.example")

    def test_refuses_a_symlinked_domain_folder(self):  # review3 F4
        elsewhere = pathlib.Path(self.tmp.name) / "elsewhere"
        elsewhere.mkdir()
        make_domain(elsewhere)
        (self.root / "x.example").symlink_to(elsewhere / "x.example")
        with self.assertRaisesRegex(B.BuildError, "x.example"):
            B.build(self.root, self.out)

    def test_refuses_an_impossible_fetch_date(self):
        run = make_domain(self.root) / "runs" / "r-1"
        data = json.loads((run / "run.json").read_text(encoding="utf-8"))
        (run / "run.json").write_text(json.dumps({**data, "fetched_at": "2026-13-45T10:00:00Z"}), encoding="utf-8")
        with self.assertRaisesRegex(B.BuildError, "fetched_at"):
            B.checked_date(run)

    def _fetched_at(self, value):
        run = make_domain(self.root) / "runs" / "r-1"
        data = json.loads((run / "run.json").read_text(encoding="utf-8"))
        (run / "run.json").write_text(json.dumps({**data, "fetched_at": value}), encoding="utf-8")
        return run

    def test_an_offset_fetch_time_gives_its_utc_date(self):  # QA holdout: "(UTC date)" means converted
        self.assertEqual(B.checked_date(self._fetched_at("2026-10-27T23:30:00-05:00")), "2026-10-28")

    def test_refuses_a_fetch_time_without_a_zone(self):
        with self.assertRaisesRegex(B.BuildError, "fetched_at"):
            B.checked_date(self._fetched_at("2026-10-30T10:00:00"))

    def test_the_change_log_comes_from_changelog_md(self):
        make_domain(self.root, changelog="2026-10-30: first run.\n2026-11-02: second run, 3 claims.\n")
        B.build(self.root, self.out)
        self.assertIn("2026-10-30: first run. 2026-11-02: second run, 3 claims.",
                      (self.out / "evidence" / "x.example.html").read_text(encoding="utf-8"))

    def test_the_checked_date_is_the_fetch_date(self):
        make_domain(self.root)
        B.build(self.root, self.out)
        self.assertEqual(json.loads((self.out / "evidence" / "x.example.json").read_text(encoding="utf-8"))["checked"], "2026-10-30")
        self.assertIn("checked 2026-10-30", (self.out / "evidence" / "x.example.html").read_text(encoding="utf-8"))

    def test_front_matter_flags_reach_the_page(self):
        make_domain(self.root, front="---\npublisher: X Ltd\ncurrent_run: r-1\nself: true\n"
                                     "certificate_url: https://x.example/cert\ncertificate_note: Signed.\n---\n")
        B.build(self.root, self.out)
        page = (self.out / "evidence" / "x.example.html").read_text(encoding="utf-8")
        self.assertIn("on ourselves", page)
        self.assertIn('Signed. <a href="https://x.example/cert">', page)


class Determinism(Fixture):
    """I-1: two builds, byte-compare."""

    def test_a_clean_tree_has_no_failure(self):
        make_domain(self.root)
        self.assertEqual(B.check(self.root), [])

    def test_a_build_that_differs_between_runs_fails(self):
        make_domain(self.root)
        real = B.page_json

        def stamped(*a, **k):
            return {**real(*a, **k), "built_at": time.time_ns()}
        with mock.patch.object(B, "page_json", stamped):
            found = self.failures("I-1")
        self.assertTrue(any("evidence/x.example.json" in f for f in found), found)


class TwinParity(Fixture):
    """I-2 (VR-09): the page, its .md twin and its .json twin carry the same (id, verdict, claim text)."""

    def setUp(self):
        super().setUp()
        make_domain(self.root)

    def test_a_twin_generator_that_drops_a_row_fails_and_names_it(self):  # S-05
        real = B.render_twin

        def drops(*a, **k):
            return "\n".join(l for l in real(*a, **k).split("\n") if not l.startswith("C-002 |"))
        with mock.patch.object(B, "render_twin", drops):
            found = self.failures("I-2")
        self.assertTrue(any("C-002" in f and "x.example.md" in f for f in found), found)

    def test_a_json_twin_with_another_verdict_fails(self):
        real = B.page_json

        def flips(*a, **k):
            page = real(*a, **k)
            page["claims"] = [{**c, "verdict": "evidenced"} if c["id"] == "C-003" else c for c in page["claims"]]
            return page
        with mock.patch.object(B, "page_json", flips):
            found = self.failures("I-2")
        self.assertTrue(any("C-003" in f and "x.example.json" in f for f in found), found)

    def test_a_json_twin_with_other_claim_text_fails(self):
        real = B.page_json

        def rewords(*a, **k):
            page = real(*a, **k)
            page["claims"] = [{**c, "text": "We build boats."} if c["id"] == "C-001" else c for c in page["claims"]]
            return page
        with mock.patch.object(B, "page_json", rewords):
            found = self.failures("I-2")
        self.assertTrue(any("C-001" in f for f in found), found)

    def test_a_page_missing_a_row_fails(self):
        real = B.page_html

        def drops(*a, **k):
            html = real(*a, **k)
            start = html.index('<tr id="C-001">')
            return html[:start] + html[html.index("</tr>", start) + len("</tr>"):]
        with mock.patch.object(B, "page_html", drops):
            found = self.failures("I-2")
        self.assertTrue(any("C-001" in f for f in found), found)

    def test_a_twin_moving_a_row_to_another_verdict_fails(self):
        real = B.render_twin

        def moves(*a, **k):
            return real(*a, **k).replace("## Evidenced (1)", "## No evidence published (1)", 1)
        with mock.patch.object(B, "render_twin", moves):
            found = self.failures("I-2")
        self.assertTrue(any("C-001" in f and "x.example.md" in f for f in found), found)

    def test_a_jsonl_that_is_not_the_register_fails(self):
        real = B.page_jsonl

        def trims(*a, **k):
            return real(*a, **k).split(b"\n", 1)[1]
        with mock.patch.object(B, "page_jsonl", trims):
            found = self.failures("I-2")
        self.assertTrue(any("x.example.jsonl" in f for f in found), found)

    def test_a_row_listed_twice_fails(self):
        self._row_listed_twice()

    def _row_listed_twice(self):
        real = B.render_twin

        def doubles(*a, **k):
            md = real(*a, **k)
            line = next(l for l in md.split("\n") if l.startswith("C-003 |"))
            return md.replace(line, line + "\n\n" + line, 1)
        with mock.patch.object(B, "render_twin", doubles):
            found = self.failures("I-2")
        self.assertTrue(any("C-003" in f for f in found), found)


class TwinParityEdges(Fixture):
    """review3 F1, F8: claim text with ' | ' in it; the low-confidence section."""

    def test_claim_text_with_a_pipe_passes(self):  # r6 has 12 such claims
        make_domain(self.root, texts=("We build houses.", "Established in 1990.", "The site title is 'About | X Ltd'."))
        self.assertEqual(B.check(self.root), [])

    def test_a_twin_changing_text_after_a_pipe_fails(self):
        make_domain(self.root, texts=("We build houses.", "Established in 1990.", "The site title is 'About | X Ltd'."))
        real = B.render_twin

        def edits(*a, **k):
            return real(*a, **k).replace("About | X Ltd", "About | Y Ltd", 1)
        with mock.patch.object(B, "render_twin", edits):
            found = self.failures("I-2")
        self.assertTrue(any("C-003" in f and "x.example.md" in f for f in found), found)

    def test_a_claim_spread_over_lines_in_the_twin_still_matches(self):
        make_domain(self.root)
        real = B.render_twin

        def wraps(*a, **k):
            return real(*a, **k).replace("C-001 | We build houses.", "C-001 | We build\nhouses.", 1)
        with mock.patch.object(B, "render_twin", wraps):
            self.assertEqual(self.failures("I-2"), [])

    def test_the_low_confidence_split_passes_when_twins_agree(self):
        make_domain(self.root, low=True, front="---\npublisher: X Ltd\ncurrent_run: r-1\nsplit_low_confidence: true\n---\n")
        self.assertEqual(B.check(self.root), [])
        self.assertIn('id="contradicted-low-confidence"', (lambda out: (B.build(self.root, out),
                      (out / "evidence" / "x.example.html").read_text(encoding="utf-8"))[1])(self.out))

    def test_a_twin_folding_the_low_confidence_section_fails(self):
        make_domain(self.root, low=True, front="---\npublisher: X Ltd\ncurrent_run: r-1\nsplit_low_confidence: true\n---\n")
        real = B.render_twin

        def folds(*a, **k):
            return real(*a, **k).replace("## Contradicted, low confidence (1)", "## Contradicted (1)", 1)
        with mock.patch.object(B, "render_twin", folds):
            found = self.failures("I-2")
        self.assertTrue(any("C-002" in f and "x.example.md" in f for f in found), found)

    def test_a_json_losing_low_confidence_fails_on_a_split_page(self):
        make_domain(self.root, low=True, front="---\npublisher: X Ltd\ncurrent_run: r-1\nsplit_low_confidence: true\n---\n")
        real = B.page_json

        def drops_low(*a, **k):
            page = real(*a, **k)
            page["claims"] = [{k2: v for k2, v in c.items() if k2 != "confidence"} for c in page["claims"]]
            return page
        with mock.patch.object(B, "page_json", drops_low):
            found = self.failures("I-2")
        self.assertTrue(any("C-002" in f and "x.example.json" in f for f in found), found)

    def test_low_confidence_is_not_a_verdict_on_an_unsplit_page(self):
        make_domain(self.root, low=True)
        self.assertEqual(B.check(self.root), [])


class Manifest(Fixture):
    """I-4: every file in a run folder matches manifest.sha256, and no file is unlisted or missing."""

    def setUp(self):
        super().setUp()
        self.run = make_domain(self.root) / "runs" / "r-1"

    def test_clean(self):
        self.assertEqual(self.failures("I-4"), [])

    def test_an_edited_file_fails(self):
        with open(self.run / "claims.jsonl", "a", encoding="utf-8") as f:
            f.write("\n")
        self.assertTrue(any("claims.jsonl" in f for f in self.failures("I-4")))

    def test_an_extra_file_fails(self):
        (self.run / "notes.txt").write_text("x", encoding="utf-8")
        self.assertTrue(any("notes.txt" in f for f in self.failures("I-4")))

    def test_an_extra_file_in_a_subfolder_fails(self):
        (self.run / "sources").mkdir()
        (self.run / "sources" / "a.html").write_bytes(PAGE)
        self.assertTrue(any("sources/a.html" in f for f in self.failures("I-4")))

    def test_a_listed_file_that_is_missing_fails(self):
        (self.run / "judge.json").unlink(missing_ok=True)
        (self.run / "disprove.jsonl").unlink()
        self.assertTrue(any("disprove.jsonl" in f for f in self.failures("I-4")))

    def test_a_run_folder_without_a_manifest_fails(self):
        (self.run / "manifest.sha256").unlink()
        self.assertTrue(any("manifest.sha256" in f for f in self.failures("I-4")))

    def test_a_listed_path_outside_the_folder_fails(self):
        with open(self.run / "manifest.sha256", "a", encoding="utf-8") as f:
            f.write(f"{SHA}  ../index.md\n")
        self.assertTrue(any("../index.md" in f for f in self.failures("I-4")))

    def test_source_bytes_listed_in_the_manifest_still_fail(self):  # review3 F2: 00 §4.2, sources are never published
        add_to_manifest(self.run, "sources/a.html", PAGE)
        self.assertTrue(any("sources/a.html" in f for f in self.failures("I-4")))
        with self.assertRaisesRegex(B.BuildError, "sources/a.html"):
            B.build(self.root, self.out)

    def test_an_unpublished_record_file_listed_in_the_manifest_fails(self):
        add_to_manifest(self.run, "prompt-prove.md", b"the prompt")
        self.assertTrue(any("prompt-prove.md" in f for f in self.failures("I-4")))

    def test_a_subfolder_fails_even_when_listed(self):  # review3 F3: a forced-in __pycache__ or .git
        for folder in ("__pycache__", ".git"):
            with self.subTest(folder=folder):
                add_to_manifest(self.run, f"{folder}/notes.txt", b"x")
                self.assertTrue(any(f"{folder}/notes.txt" in f for f in self.failures("I-4")))
                with self.assertRaises(B.BuildError):
                    B.build(self.root, self.out)

    def test_a_file_listed_twice_fails(self):  # review3 F6
        lines = (self.run / "manifest.sha256").read_text(encoding="utf-8").splitlines()
        name = lines[0].split("  ", 1)[1]
        (self.run / "manifest.sha256").write_text(f"{'0' * 64}  {name}\n" + "".join(l + "\n" for l in lines), encoding="utf-8")
        self.assertTrue(any(name in f and "twice" in f for f in self.failures("I-4")))

    def test_lines_out_of_order_fail(self):
        lines = (self.run / "manifest.sha256").read_text(encoding="utf-8").splitlines()
        (self.run / "manifest.sha256").write_text("".join(l + "\n" for l in reversed(lines)), encoding="utf-8")
        self.assertTrue(any("sorted" in f for f in self.failures("I-4")))

    def test_an_unreadable_manifest_is_reported_and_the_other_checks_still_run(self):  # review3 F7
        (self.run / "manifest.sha256").write_bytes(b"\xff\xfe not text\n")
        (self.root / "leak.txt").write_text("".join(("gh", "p_abc")), encoding="utf-8")
        found = B.check(self.root)
        self.assertTrue(any(f.startswith("I-4 ") and "manifest.sha256" in f for f in found), found)
        self.assertTrue(any(f.startswith("I-8 ") and "leak.txt" in f for f in found), found)

    def test_the_build_refuses_an_edited_record(self):  # the deploy path runs the plain build; CI is advisory
        with open(self.run / "claims.jsonl", "a", encoding="utf-8") as f:
            f.write("\n")
        with self.assertRaisesRegex(B.BuildError, "claims.jsonl"):
            B.build(self.root, self.out)

    def test_every_run_is_checked_not_only_the_current_one(self):
        old = self.run.parent / "r-0"
        shutil.copytree(self.run, old)
        (old / "extra.txt").write_text("x", encoding="utf-8")
        self.assertTrue(any("r-0" in f for f in self.failures("I-4")))


class Secrets(Fixture):
    """I-8 (VR-11): the tree, the output and the build log carry none of the markers."""

    # Joined at run time: adjacent literals would be folded into whole markers in this file's bytecode cache.
    MARKERS = tuple("".join(p) for p in (("sk-", "ant-api03-x"), ("gh", "s_abc"), ("gh", "p_abc"), ("github", "_pat_abc"),
                                         ("-----", "BEGIN PRIVATE KEY-----")))

    def test_clean(self):
        make_domain(self.root)
        self.assertEqual(self.failures("I-8"), [])

    def test_a_marker_in_any_tree_file_fails(self):
        make_domain(self.root)
        for n, marker in enumerate(self.MARKERS):
            with self.subTest(marker=marker[:6]):
                path = self.root / "config" / f"leak{n}.txt"
                path.parent.mkdir(exist_ok=True)
                path.write_text(f"token={marker}\n", encoding="utf-8")
                self.assertTrue(any(f"config/leak{n}.txt" in f for f in self.failures("I-8")))
                path.unlink()

    def test_a_marker_that_reaches_the_output_fails(self):
        make_domain(self.root, texts=("We build houses.", "Established in 1990.", "Our key is " + self.MARKERS[0] + "."))
        found = self.failures("I-8")
        self.assertTrue(any("evidence/x.example.html" in f for f in found), found)

    def test_a_marker_in_the_build_log_fails(self):
        make_domain(self.root)
        real = B.build

        def noisy(*a, **k):
            return real(*a, **k) + ["token " + self.MARKERS[1]]
        with mock.patch.object(B, "build", noisy):
            found = self.failures("I-8")
        self.assertTrue(any("build log" in f for f in found), found)

    def _noisy_generator(self):
        """A page generator that prints a marker to stdout and stderr while it builds (QA holdout)."""
        real, marker = B.G.build, self.MARKERS[0]

        def noisy(*a, **k):
            print("diag", marker)
            print("diag", marker, file=sys.stderr)
            return real(*a, **k)
        return mock.patch.object(B.G, "build", noisy), marker

    def test_generator_output_is_part_of_the_scanned_build_log_and_never_printed(self):
        make_domain(self.root)
        patch, marker = self._noisy_generator()
        seen = io.StringIO()
        with patch, contextlib.redirect_stdout(seen), contextlib.redirect_stderr(seen):
            found = self.failures("I-8")
        self.assertTrue(any("build log" in f for f in found), found)
        self.assertNotIn(marker, seen.getvalue())
        self.assertFalse(any(marker in f for f in found))

    def test_a_plain_build_with_a_marker_in_its_log_fails_without_printing_it(self):  # the deploy path
        make_domain(self.root)
        patch, marker = self._noisy_generator()
        seen = io.StringIO()
        with patch, contextlib.redirect_stdout(seen), contextlib.redirect_stderr(seen):
            code = B.main(["--root", str(self.root), "--out", str(self.out)])
        self.assertEqual(code, 1)
        self.assertNotIn(marker, seen.getvalue())
        self.assertIn("secret marker", seen.getvalue())

    def test_clean_generator_output_stays_in_the_log(self):
        make_domain(self.root)
        real = B.G.build

        def chatty(*a, **k):
            print("building page")
            return real(*a, **k)
        with mock.patch.object(B.G, "build", chatty), contextlib.redirect_stdout(io.StringIO()):
            log = B.build(self.root, self.out)
        self.assertTrue(any("building page" in line for line in log), log)

    def test_only_the_root_git_folder_is_skipped(self):  # review3 F3
        make_domain(self.root)
        (self.root / ".git").mkdir()
        (self.root / ".git" / "f").write_text(self.MARKERS[2], encoding="utf-8")
        self.assertEqual(self.failures("I-8"), [])
        for folder in ("tools/__pycache__", "config/.git"):
            with self.subTest(folder=folder):
                (self.root / folder).mkdir(parents=True)
                (self.root / folder / "f").write_text(self.MARKERS[2], encoding="utf-8")
                self.assertTrue(any(f"{folder}/f" in f for f in self.failures("I-8")))
                (self.root / folder / "f").unlink()


class Cli(Fixture):
    """The command line: what a deploy and CI actually run."""

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = B.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_a_build_prints_its_log_and_exits_0(self):
        make_domain(self.root)
        code, out, err = self.run_main("--root", str(self.root), "--out", str(self.out))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("wrote evidence/x.example.html", out)
        self.assertTrue((self.out / "evidence" / "x.example.html").is_file())

    def test_the_default_output_is_dist_under_the_root(self):
        make_domain(self.root)
        self.assertEqual(self.run_main("--root", str(self.root))[0], 0)
        self.assertTrue((self.root / "dist" / "evidence" / "x.example.html").is_file())

    def test_a_refused_build_exits_1_with_the_reason_on_stderr(self):
        make_domain(self.root, front="---\npublisher: X Ltd\ncurrent_run: r-9\n---\n")
        code, out, err = self.run_main("--root", str(self.root), "--out", str(self.out))
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("build: ") and "r-9" in err, err)

    def test_a_refusal_naming_a_marker_withholds_it(self):
        marker = "".join(("gh", "p_abc"))
        make_domain(self.root, front=f"---\npublisher: X Ltd\ncurrent_run: r-1\n{marker}: x\n---\n")
        code, out, err = self.run_main("--root", str(self.root), "--out", str(self.out))
        self.assertEqual(code, 1)
        self.assertNotIn(marker, out + err)
        code, out, err = self.run_main("--root", str(self.root), "--check")
        self.assertEqual(code, 1)
        self.assertNotIn(marker, out + err)
        self.assertIn("I-8 x.example/index.md", out)

    def test_check_clean_prints_the_count_and_exits_0(self):
        make_domain(self.root)
        self.assertEqual(self.run_main("--root", str(self.root), "--check"), (0, "check: 0 failure(s)\n", ""))

    def test_check_red_prints_each_failure_then_the_count_and_exits_1(self):
        run = make_domain(self.root) / "runs" / "r-1"
        (run / "notes.txt").write_text("x", encoding="utf-8")
        code, out, _err = self.run_main("--root", str(self.root), "--check")
        lines = out.splitlines()
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1], f"check: {len(lines) - 1} failure(s)")
        self.assertTrue(any(l.startswith("I-4 x.example/runs/r-1/notes.txt") for l in lines), lines)

    def test_check_takes_no_out(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            B.main(["--root", str(self.root), "--check", "--out", str(self.out)])

    def test_the_default_root_is_the_repo_and_the_script_runs(self):
        import subprocess
        done = subprocess.run([sys.executable, "-I", "-B", str(TOOLS / "build.py"), "--check"], capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout),
                         (1 if REPO_FAILURES else 0, "".join(f + "\n" for f in REPO_FAILURES) + f"check: {len(REPO_FAILURES)} failure(s)\n"),
                         done.stderr)


class Rules(Fixture):
    """Edges of the front matter, the domain and run-id patterns, and the log."""

    def write(self, text):
        path = self.root / "index.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_refusal_messages_say_what_and_where(self):
        for text, said in (("---\npublisher: A\ncurrent_run: r-1\n", "no front matter"),  # one fence only
                           ("---\npublisher: A\ncurrent_run: r-1\njust words\n---\n", "index.md:4: not a key: value line"),
                           ("---\npublisher: A\ncurrent_run: r-1\ncolour: red\n---\n", "index.md:4: unknown key colour"),
                           ("---\npublisher: A\npublisher: B\ncurrent_run: r-1\n---\n", "index.md:3: publisher given twice"),
                           ("---\npublisher: A\ncurrent_run: r-\n---\n", "is not a run id")):
            with self.subTest(said=said), self.assertRaises(B.BuildError) as caught:
                B.front_matter(self.write(text))
            self.assertIn(said, str(caught.exception))

    def test_blank_lines_inside_the_front_matter_are_fine(self):
        self.assertEqual(B.front_matter(self.write("---\npublisher: A\n\ncurrent_run: r-1\n---\n"))["current_run"], "r-1")

    def test_a_missing_run_folder_is_named_as_such(self):
        make_domain(self.root, front="---\npublisher: X Ltd\ncurrent_run: r-9\n---\n")
        with self.assertRaisesRegex(B.BuildError, "current_run r-9 has no folder"):
            B.build(self.root, self.out)

    def test_only_whole_domain_names_are_domain_folders(self):
        make_domain(self.root)
        for name in (".example", "x.example_old", "notes", "X.example"):
            (self.root / name).mkdir()
        self.assertEqual([d for d, _m, _r in B.domains(self.root)], ["x.example"])
        B.build(self.root, self.out)

    def test_the_log_names_each_file_with_its_size_and_each_record_copy(self):
        make_domain(self.root)
        log = B.build(self.root, self.out)
        for line in log:
            if line.startswith("wrote "):
                _w, rel, size, unit = line.split(" ")
                self.assertEqual((int(size), unit), ((self.out / rel).stat().st_size, "B"))
        copied = [l for l in log if l.startswith("copied ")]
        run = self.root / "x.example" / "runs" / "r-1"
        self.assertEqual(copied, [f"copied evidence/x.example/runs/r-1/ {len(list(run.iterdir()))} files"])
        written = {l.split(" ")[1] for l in log if l.startswith("wrote ")}
        self.assertLessEqual({f"evidence/x.example.{ext}" for ext in ("html", "md", "json", "jsonl")}, written)

    def test_non_ascii_stays_readable_in_the_json(self):
        make_domain(self.root, texts=("We build houses.", "Established in 1990.", "Café owners’ choice."))
        B.build(self.root, self.out)
        self.assertIn("Café owners’ choice.", (self.out / "evidence" / "x.example.json").read_text(encoding="utf-8"))

    def test_the_json_twins_are_byte_stable(self):  # regression goldens: indent, key order, trailing newline
        B.build(REPO, self.out)
        for domain, *_ in THIRD_PARTY:
            with self.subTest(domain=domain):
                self.assertEqual((self.out / "evidence" / f"{domain}.json").read_bytes(),
                                 (TOOLS / "tests" / "goldens" / "build-2026-11-02" / f"{domain}.json").read_bytes())


class ParityEdges(Fixture):
    """I-2 edges: private evidence, whitespace, headings without verdicts, duplicates on the page, I-1's file sets."""

    def private_domain(self):
        domain = make_domain(self.root)
        src = self.root.parent / "src-x.example"
        (src / "private-evidence.json").write_text(json.dumps({"C-003": {"holder": "X Ltd", "sha256": "a" * 64,
                                                                         "shown": "2026-10-30", "seen_by": "s", "note": "a report"}}),
                                                   encoding="utf-8")
        shutil.rmtree(domain / "runs" / "r-1")
        IMPORT.import_run(src, domain / "runs" / "r-1", "x.example", "X Ltd", "r-1")

    def test_an_evidence_private_claim_passes(self):
        self.private_domain()
        self.assertEqual(B.check(self.root), [])
        B.build(self.root, self.out)
        self.assertIn('id="evidence-private"', (self.out / "evidence" / "x.example.html").read_text(encoding="utf-8"))
        counts = json.loads((self.out / "evidence" / "x.example.json").read_text(encoding="utf-8"))["counts"]
        self.assertEqual((counts["evidence_private"], counts["no_evidence_published"], counts["total"]), (1, 0, 3))

    def test_a_twin_calling_a_private_claim_no_evidence_fails(self):
        self.private_domain()
        real = B.render_twin

        def renames(*a, **k):
            return real(*a, **k).replace("## Evidence private (1)", "## No evidence published (1)", 1)
        with mock.patch.object(B, "render_twin", renames):
            self.assertTrue(any("C-003" in f for f in self.failures("I-2")))

    def test_whitespace_inside_a_claim_does_not_count(self):
        make_domain(self.root, texts=("We  build houses.", "Established in 1990.", "We are the best."))
        self.assertEqual(B.check(self.root), [])

    def test_a_row_under_a_heading_that_is_not_a_verdict_is_not_counted(self):
        make_domain(self.root)
        real = B.render_twin

        def moves(*a, **k):
            md = real(*a, **k)
            line = next(l for l in md.split("\n") if l.startswith("C-003 |"))
            return md.replace(line + "\n", "", 1).replace("## Sources as fetched", "## Sources as fetched\n\n" + line, 1)
        with mock.patch.object(B, "render_twin", moves):
            self.assertTrue(any("C-003" in f and "missing here" in f for f in self.failures("I-2")))

    def test_a_verdict_heading_without_its_count_is_not_a_verdict_heading(self):
        make_domain(self.root)
        real = B.render_twin
        with mock.patch.object(B, "render_twin", lambda *a, **k: real(*a, **k).replace("## Evidenced (1)", "## Evidenced ()", 1)):
            self.assertTrue(any("C-001" in f for f in self.failures("I-2")))

    def test_a_page_listing_a_row_twice_fails(self):
        make_domain(self.root)
        real = B.page_html

        def doubles(*a, **k):
            html = real(*a, **k)
            start = html.index('<tr id="C-001">')
            row = html[start:html.index("</tr>", start) + len("</tr>")]
            return html.replace(row, row + row, 1)
        with mock.patch.object(B, "page_html", doubles):
            self.assertTrue(any(f.startswith("I-2 evidence/x.example.html: C-001 listed 2 times") for f in self.failures("I-2")))

    def test_a_file_only_one_build_writes_fails_i1(self):
        make_domain(self.root)
        real, calls = B.build, []

        def second_adds(root, out):
            log = real(root, out)
            calls.append(out)
            if len(calls) == 2:
                (pathlib.Path(out) / "evidence" / "extra.txt").write_text("x", encoding="utf-8")
            return log
        with mock.patch.object(B, "build", second_adds):
            self.assertTrue(any("evidence/extra.txt" in f for f in self.failures("I-1")))

    def test_a_failed_build_is_reported_and_names_the_file(self):
        make_domain(self.root, front="---\npublisher: X Ltd\ncurrent_run: r-1\ncolour: red\n---\n")
        self.assertTrue(any(f.startswith("build BuildError") and "index.md" in f for f in B.check(self.root)))


class ManifestLines(Fixture):
    def setUp(self):
        super().setUp()
        self.run = make_domain(self.root) / "runs" / "r-1"
        self.lines = (self.run / "manifest.sha256").read_text(encoding="utf-8").splitlines()

    def with_extra(self, extra):
        (self.run / "manifest.sha256").write_text("".join(l + "\n" for l in self.lines) + extra, encoding="utf-8")
        return self.failures("I-4")

    def test_a_trailing_blank_line_is_fine(self):
        self.assertEqual(self.with_extra("\n"), [])

    def test_malformed_lines_are_named_by_number(self):
        n = len(self.lines)
        found = self.with_extra(f"xyz  run.json\n{SHA}run.json\n{SHA}  \n")
        for k in (n + 1, n + 2, n + 3):
            self.assertTrue(any(f"manifest.sha256:{k}: not a hash and a path" in f for f in found), (k, found))

    def test_an_absolute_path_is_outside_the_folder(self):
        self.assertTrue(any("/etc/hostname is outside the run folder" in f for f in self.with_extra(f"{SHA}  /etc/hostname\n")))

    def test_a_symlink_in_a_run_folder_fails_i4(self):
        outside = pathlib.Path(self.tmp.name) / "outside.txt"
        outside.write_text("x", encoding="utf-8")
        (self.run / "judge.json").symlink_to(outside)
        self.assertTrue(any("judge.json: a symlink" in f for f in self.failures("I-4")))


class MutationRound2(Fixture):
    """One test per behaviour-level survivor of the second mutation sweep (argus-claims-qa/mutation-build/survivors-2.txt)."""

    def setUp(self):
        super().setUp()
        self.run = make_domain(self.root) / "runs" / "r-1"

    # Written out from 00-overview §4.2 (plus the importer's three), not read from build.PUBLISHED: a test that loops over
    # the code's own list cannot notice an entry missing from it (mutation round 3).
    SPEC_PUBLISHED = ("run.json", "sources.sha256", "http-cache.json", "claims.jsonl", "claims.md", "lister-rejects.jsonl",
                      "checks.jsonl", "checks-summary.md", "prove.jsonl", "disprove.jsonl", "tool-fetches.json",
                      "verdicts.jsonl", "register.jsonl", "todo.json", "report.md", "gates.json", "MOVEMENT.md",
                      "movement.json", "model-calls.jsonl", "judge.json", "private-evidence.json", "prove-summary.md",
                      "disprove-summary.md")

    def test_every_published_record_file_passes_i4(self):
        self.assertEqual(len(set(self.SPEC_PUBLISHED)), 23)
        for name in self.SPEC_PUBLISHED:
            if not (self.run / name).exists():
                add_to_manifest(self.run, name, b"{}\n" if name.endswith(".json") else b"x\n")
        self.assertEqual(B.check(self.root), [])

    def test_a_published_file_missing_from_the_manifest_fails(self):
        (self.run / "todo.json").write_text("[]\n", encoding="utf-8")
        self.assertIn("I-4 x.example/runs/r-1/todo.json: not listed in manifest.sha256", self.failures("I-4"))

    def test_a_missing_or_symlinked_manifest_is_named(self):
        manifest = self.run / "manifest.sha256"
        copy = pathlib.Path(self.tmp.name) / "manifest-copy"
        copy.write_bytes(manifest.read_bytes())
        manifest.unlink()
        self.assertIn("I-4 x.example/runs/r-1/manifest.sha256: missing", self.failures("I-4"))
        manifest.symlink_to(copy)
        self.assertIn("I-4 x.example/runs/r-1/manifest.sha256: missing", self.failures("I-4"))

    def test_an_empty_subfolder_fails(self):
        (self.run / "spare").mkdir()
        self.assertIn("I-4 x.example/runs/r-1/spare: a subfolder (a run folder is flat)", self.failures("I-4"))

    def test_a_manifest_name_with_a_trailing_blank_is_not_the_file(self):
        lines = (self.run / "manifest.sha256").read_text(encoding="utf-8").splitlines()
        lines[0] += " "
        (self.run / "manifest.sha256").write_text("".join(l + "\n" for l in lines), encoding="utf-8")
        self.assertTrue(any("not listed in manifest.sha256" in f for f in self.failures("I-4")))

    def test_a_parent_path_is_outside_the_folder(self):
        with open(self.run / "manifest.sha256", "a", encoding="utf-8") as f:
            f.write(f"{SHA}  sources/../../index.md\n")
        self.assertTrue(any("sources/../../index.md is outside the run folder" in f for f in self.failures("I-4")))

    def test_a_symlinked_runs_folder_is_not_followed_by_i4(self):
        elsewhere = pathlib.Path(self.tmp.name) / "elsewhere"
        shutil.copytree(self.run.parent, elsewhere)
        (elsewhere / "r-1" / "stray.txt").write_text("x", encoding="utf-8")
        shutil.rmtree(self.run.parent)
        (self.root / "x.example" / "runs").symlink_to(elsewhere)
        self.assertFalse(any("stray.txt" in f for f in B.manifests(self.root)))
        with self.assertRaises(B.BuildError):
            B.build(self.root, self.out)

    def test_i4_reports_a_symlinked_domain_folder_without_following_it(self):
        elsewhere = pathlib.Path(self.tmp.name) / "elsewhere"
        shutil.move(str(self.root / "x.example"), str(elsewhere))
        (elsewhere / "runs" / "r-1" / "stray.txt").write_text("x", encoding="utf-8")
        (self.root / "x.example").symlink_to(elsewhere)
        self.assertEqual(B.manifests(self.root), ["I-4 x.example: a domain folder that is a symlink (not followed)"])

    def test_a_step_that_crashes_is_reported_under_its_own_name(self):
        for name, fn in (("I-1", "determinism"), ("I-2", "parity"), ("I-4", "manifests"), ("I-8", "secrets")):
            with self.subTest(step=name), mock.patch.object(B, fn, side_effect=RuntimeError("boom")):
                self.assertIn(f"{name} could not run: RuntimeError: boom", B.check(self.root))

    def test_the_verdict_message_names_both_readings(self):
        real = B.render_twin
        with mock.patch.object(B, "render_twin",
                               lambda *a, **k: real(*a, **k).replace("## Evidenced (1)", "## No evidence published (1)", 1)):
            self.assertIn("I-2 evidence/x.example.md: C-001 reads no_evidence_published, the page reads evidenced",
                          self.failures("I-2"))

    def test_a_bool_refusal_names_its_line(self):
        path = self.root / "index.md"
        path.write_text("---\npublisher: A\ncurrent_run: r-1\nself: yes\n---\n", encoding="utf-8")
        with self.assertRaisesRegex(B.BuildError, "index.md:4: self must be true or false"):
            B.front_matter(str(path))  # a str path works too

    def test_the_refused_plain_build_says_so_exactly(self):
        real, marker = B.G.build, "".join(("gh", "p_abc"))

        def noisy(*a, **k):
            print(marker)
            return real(*a, **k)
        err = io.StringIO()
        with mock.patch.object(B.G, "build", noisy), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(B.main(["--root", str(self.root), "--out", str(self.out)]), 1)
        self.assertEqual(err.getvalue(), "build: the build log carries a secret marker (not printed); the build is refused\n")

    def test_text_that_cannot_be_encoded_is_scanned_without_crashing(self):
        self.assertFalse(B._has_marker("half a pair \ud800 here"))


class PageAndTwinReaders(unittest.TestCase):
    """The two row readers I-2 rests on, on hand-written input."""

    def test_page_rows_with_whitespace_nested_tags_and_short_rows(self):
        html = ('<section id="evidenced"><table><tr id="C-001">\n  <td>C-001</td> <td>Text <b>bold</b> end</td><td>x</td></tr>'
                '<tr id="C-002"><td>C-002</td></tr><tr id="C-003"><td>C-003</td><td>Two cells</td></tr></table></section>'
                '<section id="sources"><tr id="C-004"><td>C-004</td><td>Stray</td></tr></section>')
        self.assertEqual(B.html_rows(html), [("C-001", "evidenced", "Text bold end"), ("C-002", "evidenced", ""),
                                             ("C-003", "evidenced", "Two cells"),
                                             ("C-004", "outside a verdict section (sources)", "Stray")])

    def test_a_twin_row_ends_at_a_blank_line(self):
        md = "## Evidenced (1)\n\nC-001 | Text | made\nmore made | cell |\n\nstray line\n\n## Sources as fetched\n\nC-002 | x |\n"
        self.assertEqual(B.md_rows(md), [("C-001", "evidenced", "Text | made more made | cell |")])


class SecretLabels(Fixture):
    MARKER = "".join(("gh", "s_abc"))

    def test_an_output_hit_is_labelled_dist(self):
        make_domain(self.root, texts=("We build houses.", "Established in 1990.", "Key " + self.MARKER + "."))
        self.assertIn("I-8 dist/evidence/x.example.html: carries a secret marker", self.failures("I-8"))

    def test_a_log_hit_names_its_line(self):
        make_domain(self.root)
        lines = len(B.build(self.root, self.out))
        real = B.build
        with mock.patch.object(B, "build", lambda *a, **k: real(*a, **k) + ["token " + self.MARKER]):
            found = self.failures("I-8")
        self.assertEqual(found, [f"I-8 build log line {lines + 1}: carries a secret marker",
                                 f"I-8 build log line {2 * lines + 2}: carries a secret marker"])

    def test_a_symlink_in_the_tree_is_not_followed(self):
        make_domain(self.root)
        outside = pathlib.Path(self.tmp.name) / "outside.txt"
        outside.write_text(self.MARKER, encoding="utf-8")
        (self.root / "config" / "link.txt").symlink_to(outside)
        self.assertEqual(self.failures("I-8"), [])


if __name__ == "__main__":
    unittest.main()
