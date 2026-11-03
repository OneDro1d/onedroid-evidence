"""Tests for the record checks I-3, I-5, I-6, I-9 in tools/build.py (argus-claims 02-sa-service-map §5.3; VR-06,
VR-08, VR-09)."""
import hashlib
import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from test_build import B, IMPORT, TOOLS, REPO, clean_kit, make_domain, jsonl


def notepad_run(path, domain, ids, fetched_at):
    """A notepad-style run whose claims all read NO EVIDENCE PUBLISHED, with the given ids."""
    page = f"<html>{domain} {fetched_at}</html>".encode()
    sha = hashlib.sha256(page).hexdigest()
    (path / "sources").mkdir(parents=True)
    (path / "sources" / "a.html").write_bytes(page)
    (path / "claims.md").write_text("| source URL | local file | HTTP | bytes | sha256 |\n|---|---|---|---|---|\n"
                                    f"| https://{domain}/ | sources/a.html | 200 | {len(page)} | {sha} |\n", encoding="utf-8")
    (path / "claims.jsonl").write_text(jsonl([{"id": i, "claim": f"Claim {i}.", "kind": "capability", "checkability": "A",
                                               "sources": [{"url": f"https://{domain}/", "locator": "body"}]} for i in ids]),
                                       encoding="utf-8")
    (path / "prove.jsonl").write_text(jsonl([{"id": i, "evidence": "none", "refs": [], "note": "n"} for i in ids]), encoding="utf-8")
    (path / "disprove.jsonl").write_text(jsonl([{"id": i, "contradiction": "no", "refs": [], "note": "n"} for i in ids]),
                                         encoding="utf-8")
    (path / "run.json").write_text(json.dumps({"fetched_at": fetched_at}), encoding="utf-8")
    return path


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.domain = make_domain(self.root)
        self.kit_patch = mock.patch.object(B, "KIT", clean_kit(pathlib.Path(self.tmp.name) / "kit"))
        self.kit_patch.start()

    def tearDown(self):
        self.kit_patch.stop()
        self.tmp.cleanup()

    def add_run(self, run_id, ids, fetched_at, previous=None):
        src = notepad_run(pathlib.Path(self.tmp.name) / f"src-{run_id}", "x.example", ids, fetched_at)
        IMPORT.import_run(src, self.domain / "runs" / run_id, "x.example", "X Ltd", run_id, baseline_run_id=previous)
        return self.domain / "runs" / run_id

    def failures(self, invariant, **kw):
        return [f for f in B.check(self.root, **kw) if f.startswith(invariant + " ")]


class VerdictRecompute(Fixture):
    """I-3: verdicts.jsonl is what verdict.py makes of the passes, with the rule the rows record."""

    def setUp(self):
        super().setUp()
        self.run = self.domain / "runs" / "r-1"

    def rewrite(self, name, change):
        rows = [json.loads(l) for l in (self.run / name).read_text(encoding="utf-8").splitlines()]
        (self.run / name).write_text(jsonl([change(r) for r in rows]), encoding="utf-8")

    def test_clean(self):
        self.assertEqual(self.failures("I-3"), [])

    def test_a_verdict_the_passes_do_not_give_fails(self):
        self.rewrite("verdicts.jsonl", lambda r: {**r, "verdict": "EVIDENCED"} if r["id"] == "C-003" else r)
        self.assertIn("I-3 x.example/runs/r-1/verdicts.jsonl: C-003 records EVIDENCED, the passes give NO EVIDENCE PUBLISHED",
                      self.failures("I-3"))

    def test_an_edited_pass_fails(self):
        self.rewrite("prove.jsonl", lambda r: {**r, "evidence": "artefact"} if r["id"] == "C-003" else r)
        self.assertTrue(any("C-003" in f for f in self.failures("I-3")))

    def test_a_ruling_counts(self):
        (self.run / "judge.json").write_text(json.dumps({"C-003": {"verdict": "EVIDENCED", "note": "seen"}}), encoding="utf-8")
        self.assertTrue(any("C-003" in f for f in self.failures("I-3")))  # verdicts.jsonl predates the ruling

    def test_a_missing_or_extra_row_fails(self):
        rows = (self.run / "verdicts.jsonl").read_text(encoding="utf-8").splitlines()
        (self.run / "verdicts.jsonl").write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")
        self.assertTrue(any("C-003" in f for f in self.failures("I-3")))

    def test_the_recorded_rule_is_used(self):  # the fixture's contradiction has no low note: both rules agree, so flip one
        self.rewrite("disprove.jsonl", lambda r: {**r, "note": "low confidence: dates"} if r["id"] == "C-002" else r)
        self.assertTrue(any("C-002" in f for f in self.failures("I-3")))  # note-text now reads low; the rows say not low

    def test_two_rules_or_an_unknown_rule_fail(self):
        for change, said in ((lambda r: {**r, "rule": "confidence-field"} if r["id"] == "C-001" else r,
                              "rows record confidence-field, note-text, this record's rule is note-text"),
                             (lambda r: {**r, "rule": "guess"}, "rows record guess, this record's rule is note-text")):
            with self.subTest(said=said):
                original = (self.run / "verdicts.jsonl").read_bytes()
                self.rewrite("verdicts.jsonl", change)
                self.assertTrue(any(said in f for f in self.failures("I-3")), self.failures("I-3"))
                (self.run / "verdicts.jsonl").write_bytes(original)

    def test_the_rule_is_the_records_not_the_rows(self):  # review4 Q6
        fresh = [json.dumps(V_row) for V_row in B.V.load_run(self.run, "confidence-field")]
        (self.run / "verdicts.jsonl").write_text("\n".join(fresh) + "\n", encoding="utf-8")
        self.assertIn("I-3 x.example/runs/r-1/verdicts.jsonl: rows record confidence-field, this record's rule is note-text",
                      self.failures("I-3"))
        data = json.loads((self.run / "run.json").read_text(encoding="utf-8"))
        (self.run / "run.json").write_text(json.dumps({k: v for k, v in data.items() if k != "imported"}), encoding="utf-8")
        self.assertEqual([f for f in self.failures("I-3") if "verdicts.jsonl" in f], [])  # not imported: confidence-field

    def test_the_register_must_agree_with_the_verdicts(self):
        self.rewrite("register.jsonl", lambda r: {**r, "verdict": "evidenced"} if r["id"] == "C-003" else r)
        self.assertIn("I-3 x.example/runs/r-1/register.jsonl: C-003 reads evidenced, verdicts.jsonl reads NO EVIDENCE PUBLISHED",
                      self.failures("I-3"))

    def test_the_register_low_confidence_must_agree(self):
        self.rewrite("register.jsonl", lambda r: {**r, "confidence": "low"} if r["id"] == "C-002" else r)
        self.assertIn("I-3 x.example/runs/r-1/register.jsonl: C-002 low confidence differs from verdicts.jsonl", self.failures("I-3"))

    def test_the_register_lists_exactly_the_unwithdrawn_claims(self):
        rows = (self.run / "register.jsonl").read_text(encoding="utf-8").splitlines()
        (self.run / "register.jsonl").write_text("\n".join(rows[1:]) + "\n", encoding="utf-8")
        self.assertIn("I-3 x.example/runs/r-1/register.jsonl: C-001 missing", self.failures("I-3"))

    def test_a_row_that_is_not_an_object_is_reported_not_crashed(self):
        with open(self.run / "verdicts.jsonl", "a", encoding="utf-8") as f:
            f.write("[1, 2]\n")
        self.assertIn("I-3 x.example/runs/r-1/verdicts.jsonl: not JSON lines of objects", self.failures("I-3"))

    def test_a_missing_verdicts_file_fails(self):
        (self.run / "verdicts.jsonl").unlink()
        self.assertIn("I-3 x.example/runs/r-1/verdicts.jsonl: missing", self.failures("I-3"))

    def test_every_run_is_recomputed(self):
        old = self.add_run("r-0", ["C-001"], "2026-10-01T00:00:00Z")
        rows = [json.loads(l) for l in (old / "verdicts.jsonl").read_text(encoding="utf-8").splitlines()]
        (old / "verdicts.jsonl").write_text(jsonl([{**r, "verdict": "EVIDENCED"} for r in rows]), encoding="utf-8")
        self.assertTrue(any("r-0" in f for f in self.failures("I-3")))

    def test_the_real_records_recompute(self):
        self.assertEqual([f for f in B.verdict_recompute(REPO)], [])


class Ids(Fixture):
    """I-6 (VR-06): an id is carried from the run's previous_run or is new, above every earlier id; never reused."""

    def test_clean_single_run(self):
        self.assertEqual(self.failures("I-6"), [])

    def test_carried_and_new_ids_pass(self):
        self.add_run("r-2", ["C-001", "C-003", "C-004"], "2026-11-01T00:00:00Z", previous="r-1")
        self.assertEqual(self.failures("I-6"), [])

    def test_a_retired_id_coming_back_fails(self):
        self.add_run("r-2", ["C-001", "C-004"], "2026-11-01T00:00:00Z", previous="r-1")   # C-002, C-003 retired
        self.add_run("r-3", ["C-001", "C-003", "C-004"], "2026-11-02T00:00:00Z", previous="r-2")
        self.assertIn("I-6 x.example/runs/r-3: C-003 is neither carried from its previous_run nor above the highest earlier id", self.failures("I-6"))

    def test_a_fresh_list_must_use_new_ids(self):
        self.add_run("r-2", ["C-002", "C-004"], "2026-11-01T00:00:00Z")   # no previous_run
        self.assertIn("I-6 x.example/runs/r-2: C-002 is neither carried from its previous_run nor above the highest earlier id", self.failures("I-6"))

    def test_runs_are_ordered_by_fetch_time_not_name(self):
        self.add_run("r-0", ["C-001", "C-002", "C-003", "C-004"], "2026-11-01T00:00:00Z", previous="r-1")  # later, despite its name
        self.assertEqual(self.failures("I-6"), [])

    def test_a_baseline_that_is_not_earlier_fails(self):
        self.add_run("r-2", ["C-001"], "2026-10-01T00:00:00Z", previous="r-1")   # r-1 is fetched later
        self.assertIn("I-6 x.example/runs/r-2: baseline r-1 is not the run before it (none)", self.failures("I-6"))

    def test_a_baseline_that_does_not_exist_fails(self):
        self.add_run("r-2", ["C-001"], "2026-11-01T00:00:00Z", previous="r-9")
        self.assertIn("I-6 x.example/runs/r-2: baseline r-9 is not the run before it (r-1)", self.failures("I-6"))

    def set_run_json(self, run, **fields):
        data = json.loads((run / "run.json").read_text(encoding="utf-8"))
        (run / "run.json").write_text(json.dumps({**data, **fields}), encoding="utf-8")

    def test_a_baseline_skipping_the_run_before_cannot_bring_a_retired_id_back(self):  # review4 Q3(a)
        self.add_run("r-2", ["C-001", "C-002"], "2026-11-01T00:00:00Z", previous="r-1")   # C-003 retired
        self.add_run("r-3", ["C-001", "C-002", "C-003"], "2026-11-02T00:00:00Z", previous="r-1")
        found = self.failures("I-6")
        self.assertIn("I-6 x.example/runs/r-3: baseline r-1 is not the run before it (r-2)", found)
        self.assertIn("I-6 x.example/runs/r-3: C-003 is neither carried from its previous_run nor above the highest earlier id", found)

    def test_an_own_unpublished_previous_run_is_fine_when_the_published_baseline_is_right(self):  # review4 Q3(b)
        run = self.add_run("r-2", ["C-001", "C-002", "C-003"], "2026-11-01T00:00:00Z", previous="r-own")
        self.set_run_json(run, published_baseline="r-1")
        self.assertEqual(self.failures("I-6"), [])

    def test_the_first_run_names_no_baseline(self):
        self.set_run_json(self.domain / "runs" / "r-1", previous_run="r-0")
        self.assertIn("I-6 x.example/runs/r-1: baseline r-0 is not the run before it (none)", self.failures("I-6"))

    def test_a_missing_or_zoneless_fetch_time_fails(self):
        for value in (None, "2026-10-30T10:00:00"):
            with self.subTest(value=value):
                self.set_run_json(self.domain / "runs" / "r-1", fetched_at=value)
                self.assertIn("I-6 x.example/runs/r-1: fetched_at is missing or has no zone", self.failures("I-6"))

    def test_ids_compare_as_numbers(self):
        self.add_run("r-2", [f"C-{n:03d}" for n in range(1, 4)] + ["C-1000"], "2026-11-01T00:00:00Z", previous="r-1")
        self.add_run("r-3", ["C-999"], "2026-11-02T00:00:00Z", previous="r-2")   # below C-1000, never seen: a reuse? no, never issued
        self.assertIn("I-6 x.example/runs/r-3: C-999 is neither carried from its previous_run nor above the highest earlier id", self.failures("I-6"))


class ToolkitPin(Fixture):
    """I-9: the vendored toolkit equals its MANIFEST, TOOLKIT_VERSION names that MANIFEST, and config/exclusions.json
    equals each current run's exclusions."""

    def setUp(self):
        super().setUp()
        self.kit = pathlib.Path(self.tmp.name) / "toolkit"
        shutil.copytree(B.KIT, self.kit, ignore=shutil.ignore_patterns("__pycache__"))
        self.patch = mock.patch.object(B, "KIT", self.kit)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        super().tearDown()

    def test_clean(self):
        self.assertEqual(self.failures("I-9"), [])

    def test_a_hand_edited_toolkit_file_fails(self):
        with open(self.kit / "verdict.py", "a", encoding="utf-8") as f:
            f.write("# edited\n")
        self.assertIn("I-9 tools/toolkit/verdict.py: does not match MANIFEST", self.failures("I-9"))

    def test_an_unlisted_or_missing_toolkit_file_fails(self):
        (self.kit / "extra.py").write_text("x = 1\n", encoding="utf-8")
        (self.kit / "todo.py").unlink()
        found = self.failures("I-9")
        self.assertIn("I-9 tools/toolkit/extra.py: not listed in MANIFEST", found)
        self.assertIn("I-9 tools/toolkit/todo.py: listed in MANIFEST but missing", found)

    def test_bytecode_caches_are_aside(self):
        (self.kit / "__pycache__").mkdir()
        (self.kit / "__pycache__" / "verdict.cpython-312.pyc").write_bytes(b"x")
        self.assertEqual(self.failures("I-9"), [])

    def test_a_version_that_does_not_name_the_manifest_fails(self):
        commit, _sha = (self.kit / "TOOLKIT_VERSION").read_text(encoding="utf-8").split()
        (self.kit / "TOOLKIT_VERSION").write_text(f"{commit} {'0' * 64}\n", encoding="utf-8")
        self.assertIn("I-9 tools/toolkit/TOOLKIT_VERSION: does not name this MANIFEST", self.failures("I-9"))

    def test_an_edited_manifest_with_its_file_fails_through_the_version(self):
        with open(self.kit / "verdict.py", "a", encoding="utf-8") as f:
            f.write("# edited\n")
        lines = [l if not l.endswith("  verdict.py") else f"{hashlib.sha256((self.kit / 'verdict.py').read_bytes()).hexdigest()}  verdict.py"
                 for l in (self.kit / "MANIFEST").read_text(encoding="utf-8").splitlines()]
        (self.kit / "MANIFEST").write_text("".join(l + "\n" for l in lines), encoding="utf-8")
        self.assertEqual(self.failures("I-9"), ["I-9 tools/toolkit/TOOLKIT_VERSION: does not name this MANIFEST"])

    def test_exclusions_must_match_the_current_runs(self):
        (self.root / "config" / "exclusions.json").write_text(json.dumps({"x.example": [{"kind": "markers"}]}), encoding="utf-8")
        self.assertIn("I-9 config/exclusions.json: x.example differs from its current run's run.json", self.failures("I-9"))
        (self.root / "config" / "exclusions.json").write_text("{}", encoding="utf-8")
        self.assertIn("I-9 config/exclusions.json: x.example missing", self.failures("I-9"))
        (self.root / "config" / "exclusions.json").write_text(json.dumps({"x.example": [], "y.example": []}), encoding="utf-8")
        self.assertIn("I-9 config/exclusions.json: y.example is not a domain here", self.failures("I-9"))
        (self.root / "config" / "exclusions.json").unlink()
        self.assertIn("I-9 config/exclusions.json: missing", self.failures("I-9"))

    def test_a_run_with_exclusions_is_compared(self):
        run = self.domain / "runs" / "r-1"
        rule = [{"kind": "markers", "files": ["a.md"], "start": "<!-- x -->", "end": "<!-- /x -->"}]
        data = json.loads((run / "run.json").read_text(encoding="utf-8"))
        (run / "run.json").write_text(json.dumps({**data, "exclusions": rule}), encoding="utf-8")
        self.assertTrue(any("x.example differs" in f for f in self.failures("I-9")))
        (self.root / "config" / "exclusions.json").write_text(json.dumps({"x.example": rule}), encoding="utf-8")
        self.assertEqual(self.failures("I-9"), [])

    def test_the_commit_word_must_be_a_commit(self):  # review4 Q2
        sha = hashlib.sha256((self.kit / "MANIFEST").read_bytes()).hexdigest()
        for word, said in (("x", "is not a commit id"), ("d5bcb03+local", "vendored from an uncommitted argus-claims tree")):
            with self.subTest(word=word):
                (self.kit / "TOOLKIT_VERSION").write_text(f"{word} {sha}\n", encoding="utf-8")
                self.assertIn(f"I-9 tools/toolkit/TOOLKIT_VERSION: {word} {said}", self.failures("I-9"))
        (self.kit / "TOOLKIT_VERSION").write_text(f"{'ab12' * 10} {sha}\n", encoding="utf-8")
        self.assertEqual(self.failures("I-9"), [])

    def test_the_real_toolkit_and_config_pass_but_for_an_uncommitted_pin(self):
        with mock.patch.object(B, "KIT", TOOLS / "toolkit"):
            found = B.toolkit_pin(REPO)
            word = (B.KIT / "TOOLKIT_VERSION").read_text(encoding="utf-8").split()[0]
        self.assertEqual(found, [f"I-9 tools/toolkit/TOOLKIT_VERSION: {word} vendored from an uncommitted argus-claims tree"]
                         if word.endswith("+local") else [])


class MutationRound4(Fixture):
    """One test per behaviour-level survivor of mutation round 4 (argus-claims-qa/mutation-build/survivors-4.txt) that
    still applies to the rewritten checks: exact failure lines, boundaries, and the paths only a crash used to reach."""

    def setUp(self):
        super().setUp()
        self.run = self.domain / "runs" / "r-1"

    # I-9
    def write_manifest(self, extra):
        (B.KIT / "MANIFEST").write_text((B.KIT / "MANIFEST").read_text(encoding="utf-8") + extra, encoding="utf-8")
        sha = hashlib.sha256((B.KIT / "MANIFEST").read_bytes()).hexdigest()
        (B.KIT / "TOOLKIT_VERSION").write_text(f"0123abc {sha}\n", encoding="utf-8")

    def test_manifest_lines(self):
        self.write_manifest("\n")
        self.assertEqual(self.failures("I-9"), [])  # a blank line is fine
        n = len((B.KIT / "MANIFEST").read_text(encoding="utf-8").splitlines())
        first = (B.KIT / "MANIFEST").read_text(encoding="utf-8").splitlines()[0]
        self.write_manifest(f"{'z' * 64}  verdict.py\n{'a' * 64}verdict.py\n{'a' * 64}  \n{first}\n")
        found = self.failures("I-9")
        for k in (n + 1, n + 2, n + 3):
            self.assertIn(f"I-9 tools/toolkit/MANIFEST:{k}: not a hash and a path", found)
        self.assertIn(f"I-9 tools/toolkit/{first.split('  ')[1]}: listed twice in MANIFEST", found)

    def test_a_missing_manifest_or_version_is_named(self):
        (B.KIT / "TOOLKIT_VERSION").unlink()
        self.assertEqual(self.failures("I-9"), ["I-9 tools/toolkit/TOOLKIT_VERSION: missing"])
        (B.KIT / "MANIFEST").unlink()
        self.assertEqual(self.failures("I-9")[0], "I-9 tools/toolkit/MANIFEST: missing")

    def test_config_that_is_not_json_or_not_an_object(self):
        config = self.root / "config" / "exclusions.json"
        for text, said in (("{", "not JSON"), ("[]", "not an object of domains")):
            config.write_text(text, encoding="utf-8")
            self.assertEqual(self.failures("I-9"), [f"I-9 config/exclusions.json: {said}"])

    # I-3
    def test_verdicts_that_are_not_json(self):
        (self.run / "verdicts.jsonl").write_text("not json\n", encoding="utf-8")
        self.assertIn("I-3 x.example/runs/r-1/verdicts.jsonl: not JSON lines of objects", self.failures("I-3"))

    def test_passes_that_cannot_be_read(self):
        (self.run / "prove.jsonl").unlink()
        self.assertTrue(any(f.startswith("I-3 x.example/runs/r-1/verdicts.jsonl: the passes can't be read (") for f in self.failures("I-3")))

    def test_duplicate_and_extra_verdict_rows(self):
        rows = (self.run / "verdicts.jsonl").read_text(encoding="utf-8").splitlines()
        extra = json.dumps({**json.loads(rows[0]), "id": "C-009"})
        (self.run / "verdicts.jsonl").write_text("\n".join(rows + [rows[0], extra]) + "\n", encoding="utf-8")
        found = self.failures("I-3")
        self.assertIn("I-3 x.example/runs/r-1/verdicts.jsonl: C-001 listed twice", found)
        self.assertIn("I-3 x.example/runs/r-1/verdicts.jsonl: C-009 has a row but no claim", found)

    def test_a_wrong_rule_is_said_once(self):
        self.rewrite_rule("confidence-field")
        found = [f for f in self.failures("I-3") if "verdicts.jsonl" in f]
        self.assertEqual(found, ["I-3 x.example/runs/r-1/verdicts.jsonl: rows record confidence-field, this record's rule is note-text"])

    def rewrite_rule(self, rule):
        rows = [json.loads(l) for l in (self.run / "verdicts.jsonl").read_text(encoding="utf-8").splitlines()]
        (self.run / "verdicts.jsonl").write_text(jsonl([{**r, "rule": rule} for r in rows]), encoding="utf-8")

    def test_register_duplicates_and_extras(self):
        rows = (self.run / "register.jsonl").read_text(encoding="utf-8").splitlines()
        extra = json.dumps({**json.loads(rows[0]), "id": "C-009"})
        (self.run / "register.jsonl").write_text("\n".join(rows + [rows[0], extra]) + "\n", encoding="utf-8")
        found = self.failures("I-3")
        self.assertIn("I-3 x.example/runs/r-1/register.jsonl: C-001 listed twice", found)
        self.assertIn("I-3 x.example/runs/r-1/register.jsonl: C-009 has no published verdict", found)

    # I-6
    def add(self, run_id, ids, when, previous):
        return Fixture.add_run(self, run_id, ids, when, previous)

    def test_reusing_exactly_the_highest_earlier_id_fails(self):
        self.add("r-2", ["C-001", "C-002"], "2026-11-01T00:00:00Z", "r-1")                 # C-003 (the highest) retired
        self.add("r-3", ["C-001", "C-002", "C-003"], "2026-11-02T00:00:00Z", "r-2")
        self.assertIn("I-6 x.example/runs/r-3: C-003 is neither carried from its previous_run nor above the highest earlier id",
                      self.failures("I-6"))

    def test_bad_ids_and_an_id_listed_twice(self):
        run = self.add("r-2", ["C-001", "C-004"], "2026-11-01T00:00:00Z", "r-1")   # the importer refuses bad ids: edit after
        (run / "claims.jsonl").write_text(jsonl([{"id": i, "claim": "x", "sources": []} for i in ("C-001", "C-001", "C-000", "X-7")]),
                                          encoding="utf-8")
        found = self.failures("I-6")
        self.assertIn("I-6 x.example/runs/r-2: C-001 listed 2 times", found)
        self.assertIn("I-6 x.example/runs/r-2: 'C-000' is not a claim id", found)
        self.assertIn("I-6 x.example/runs/r-2: 'X-7' is not a claim id", found)

    def test_runs_with_the_same_fetch_time_are_ordered_by_name(self):
        self.add("r-2", ["C-001", "C-004"], "2026-11-01T00:00:00Z", "r-1")
        self.add("r-3", ["C-001", "C-005"], "2026-11-01T00:00:00Z", "r-2")
        self.assertEqual(self.failures("I-6"), [])

    def test_an_unreadable_run_is_named(self):
        (self.run / "run.json").write_text("{", encoding="utf-8")
        self.assertIn("I-6 x.example/runs/r-1: run.json or claims.jsonl unreadable (JSONDecodeError)", self.failures("I-6"))


class MutationRound5(Fixture):
    """One test per real gap left by mutation round 5 (argus-claims-qa/mutation-build/survivors-5.txt)."""

    def setUp(self):
        super().setUp()
        self.run = self.domain / "runs" / "r-1"

    def test_the_build_writes_no_bytecode_and_leaves_no_temp_folder(self):
        import os
        import sys
        private = pathlib.Path(self.tmp.name) / "private-tmp"
        private.mkdir()
        copy = pathlib.Path(self.tmp.name) / "copy"
        shutil.copytree(REPO, copy, ignore=shutil.ignore_patterns(".git", "__pycache__", "dist"))
        done = subprocess.run([sys.executable, "-I", str(copy / "tools" / "build.py"), "--out", str(pathlib.Path(self.tmp.name) / "d")],
                              capture_output=True, text=True, env={**os.environ, "TMPDIR": str(private)})
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assertEqual(list(private.iterdir()), [])                      # the private cache folder was made empty and removed
        self.assertEqual(sorted(p.name for p in copy.rglob("__pycache__")), [])

    def test_a_missing_or_unreadable_register(self):
        (self.run / "register.jsonl").write_text("not json\n", encoding="utf-8")
        self.assertIn("I-3 x.example/runs/r-1/register.jsonl: not JSON lines of objects", self.failures("I-3"))
        (self.run / "register.jsonl").unlink()
        self.assertIn("I-3 x.example/runs/r-1/register.jsonl: missing", self.failures("I-3"))

    def test_a_row_differing_only_outside_the_verdict(self):
        rows = [json.loads(l) for l in (self.run / "verdicts.jsonl").read_text(encoding="utf-8").splitlines()]
        (self.run / "verdicts.jsonl").write_text(jsonl([{**r, "ruled": True} if r["id"] == "C-001" else r for r in rows]),
                                                 encoding="utf-8")
        self.assertIn("I-3 x.example/runs/r-1/verdicts.jsonl: C-001 records ruled=True where the passes give False", self.failures("I-3"))

    def test_index_parts(self):
        self.assertEqual(B._index_parts("---\na: 1\ncurrent_run: r-1\n---\nbody\n"), (["a: 1"], ["body"]))
        self.assertEqual(B._index_parts("no front matter\n"), (["no front matter"], None))
        self.assertEqual(B._index_parts("x\n---\na: 1\n---\n"), (["x", "---", "a: 1", "---"], None))

    def test_a_literal_none_previous_run_is_a_fresh_list(self):
        run = self.add_run("r-2", ["C-002", "C-004"], "2026-11-01T00:00:00Z")
        data = json.loads((run / "run.json").read_text(encoding="utf-8"))
        (run / "run.json").write_text(json.dumps({**data, "previous_run": "none", "published_baseline": "r-1"}), encoding="utf-8")
        self.assertEqual(self.failures("I-6"),
                         ["I-6 x.example/runs/r-2: C-002 is neither carried from its previous_run nor above the highest earlier id"])

    def test_a_message_names_its_own_run_not_the_last(self):
        self.add_run("r-2", ["C-001"], "2026-11-01T00:00:00Z")                     # fresh list reusing C-001
        self.add_run("r-3", ["C-001", "C-004"], "2026-11-02T00:00:00Z", previous="r-2")
        found = self.failures("I-6")
        self.assertIn("I-6 x.example/runs/r-2: C-001 is neither carried from its previous_run nor above the highest earlier id", found)
        self.assertFalse(any(f.startswith("I-6 x.example/runs/r-3") for f in found), found)

    def test_same_time_runs_order_by_name_not_baseline(self):
        self.add_run("r-05", ["C-001", "C-004"], "2026-11-01T00:00:00Z", previous="r-1")
        self.add_run("r-06", ["C-001", "C-005"], "2026-11-01T00:00:00Z", previous="r-05")
        self.assertEqual(self.failures("I-6"), [])

    def test_a_symlinked_domain_is_not_followed_by_i6(self):
        elsewhere = pathlib.Path(self.tmp.name) / "elsewhere"
        shutil.copytree(self.domain, elsewhere)
        shutil.copytree(elsewhere / "runs" / "r-1", elsewhere / "runs" / "r-2")   # same ids again: a reuse if followed
        (self.root / "z.example").symlink_to(elsewhere)
        self.assertEqual(B.id_reuse(self.root), [])


class MutationRound5Git(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.domain = make_domain(self.root)
        make_domain(self.root, domain="y.example")
        for args in (("init", "-q"), ("config", "user.email", "t@example.invalid"), ("config", "user.name", "t"),
                     ("add", "-A"), ("commit", "-q", "-m", "base")):
            subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)
        self.base = subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()

    def tearDown(self):
        self.tmp.cleanup()

    def test_several_changes_each_get_their_own_status(self):
        run = self.domain / "runs" / "r-1"
        with open(run / "claims.jsonl", "a", encoding="utf-8") as f:
            f.write("\n")
        (run / "claims.md").unlink()
        (run / "todo.json").write_text("[]\n", encoding="utf-8")
        self.assertEqual(B.immutability(self.root, self.base),
                         ["I-5 x.example/runs/r-1/claims.jsonl: changed since the base",
                          "I-5 x.example/runs/r-1/claims.md: deleted since the base",
                          "I-5 x.example/runs/r-1/todo.json: added to a published run folder"])

    def test_an_unknown_base_is_named(self):
        self.assertEqual(B.immutability(self.root, "no-such-ref"), ["I-5 base no-such-ref: not a git commit here"])

    def test_a_publication_deleting_a_domain_file_or_the_config(self):
        (self.root / "y.example" / "index.md").unlink()
        (self.root / "config" / "exclusions.json").unlink()
        found = B.immutability(self.root, self.base, publication=True)
        self.assertIn("I-5 y.example/index.md: not part of a publication", found)
        self.assertIn("I-5 config/exclusions.json: not part of a publication", found)


class MutationRound4Publication(unittest.TestCase):
    """I-5 survivors: the exclusions entry, a force-added build folder, the repo top."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.domain = make_domain(self.root)
        make_domain(self.root, domain="y.example")
        for args in (("init", "-q"), ("config", "user.email", "t@example.invalid"), ("config", "user.name", "t"),
                     ("add", "-A"), ("commit", "-q", "-m", "base")):
            subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)
        self.base = subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        src = notepad_run(pathlib.Path(self.tmp.name) / "src-r-2", "x.example", ["C-001", "C-004"], "2026-11-01T00:00:00Z")
        IMPORT.import_run(src, self.domain / "runs" / "r-2", "x.example", "X Ltd", "r-2", baseline_run_id="r-1")
        index = self.domain / "index.md"
        index.write_text(index.read_text(encoding="utf-8").replace("current_run: r-1", "current_run: r-2"), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def i5(self, root=None):
        return B.immutability(root or self.root, self.base, publication=True)

    def set_exclusions(self, **entries):
        config = self.root / "config" / "exclusions.json"
        config.write_text(json.dumps({**json.loads(config.read_text(encoding="utf-8")), **entries}), encoding="utf-8")

    def test_a_publication_may_set_its_own_exclusions_entry(self):
        self.set_exclusions(**{"x.example": [{"kind": "markers"}]})
        self.assertEqual(self.i5(), [])

    def test_a_publication_may_not_touch_another_domains_entry(self):
        self.set_exclusions(**{"y.example": [{"kind": "markers"}]})
        self.assertEqual(self.i5(), ["I-5 config/exclusions.json: changes another domain's entry"])

    def test_a_publication_deleting_a_file_fails(self):
        (self.root / "y.example" / "changelog.md").unlink()
        self.assertIn("I-5 y.example/changelog.md: not part of a publication", self.i5())

    def test_a_force_added_build_folder_counts(self):
        (self.root / ".gitignore").write_text("dist/\n", encoding="utf-8")
        (self.root / "dist").mkdir()
        (self.root / "dist" / "page.html").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "-f", "dist/page.html"], check=True, capture_output=True)
        found = self.i5()
        self.assertIn("I-5 dist/page.html: not part of a publication", found)
        self.assertIn("I-5 .gitignore: not part of a publication", found)

    def test_a_subfolder_of_the_repo_is_refused(self):
        self.assertEqual(self.i5(self.root / "x.example"), [f"I-5 {self.root / 'x.example'}: not the top folder of its git repository"])

    def test_a_plain_change_outside_a_publication_is_fine(self):
        (self.root / "README.md").write_text("x\n", encoding="utf-8")
        self.assertEqual(B.immutability(self.root, self.base, publication=False), [])


class BytecodeCache(unittest.TestCase):
    """review4 Q1: a committed unchecked-hash .pyc beside a toolkit module must not stand in for it."""

    def test_a_planted_cache_file_does_not_change_the_page(self):
        import importlib.util
        import py_compile
        import sys
        with tempfile.TemporaryDirectory() as t:
            copy = pathlib.Path(t) / "repo"
            shutil.copytree(REPO, copy, ignore=shutil.ignore_patterns(".git", "__pycache__", "dist"))
            module = copy / "tools" / "toolkit" / "gen-evidence-page.py"
            evil = pathlib.Path(t) / "evil.py"
            evil.write_text(module.read_text(encoding="utf-8").replace("<h2>How to read this page</h2>",
                                                                       "<h2>How to read this page</h2>PLANTED-BY-PYC")
                            + "\nPLANTED = True\n", encoding="utf-8")
            # Where Python looks without a cache prefix (cache_from_source would follow this process's prefix).
            plant = module.parent / "__pycache__" / f"{module.stem}.{sys.implementation.cache_tag}.pyc"
            py_compile.compile(str(evil), cfile=str(plant), doraise=True,
                               invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
            control = subprocess.run([sys.executable, "-I", "-c",
                                      "import importlib.util, sys; s = importlib.util.spec_from_file_location('g', sys.argv[1]); "
                                      "m = importlib.util.module_from_spec(s); s.loader.exec_module(m); print(hasattr(m, 'PLANTED'))",
                                      str(module)], capture_output=True, text=True)
            self.assertEqual(control.stdout.strip(), "True", control.stderr)  # the plant works on a plain load
            done = subprocess.run([sys.executable, "-I", str(copy / "tools" / "build.py"), "--out", str(pathlib.Path(t) / "dist")],
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            page = (pathlib.Path(t) / "dist" / "evidence" / "mcmahonconstruction.ie.html").read_text(encoding="utf-8")
            self.assertNotIn("PLANTED-BY-PYC", page)


class Immutability(Fixture):
    """I-5 (VR-08): against a git base, published run folders never change; a publication adds only what it may."""

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True).stdout

    def setUp(self):
        super().setUp()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "test")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.base = self.git("rev-parse", "HEAD").strip()

    def i5(self, publication=False):
        return self.failures("I-5", base=self.base, publication=publication)

    def test_no_base_no_i5(self):
        self.assertEqual([f for f in B.check(self.root) if f.startswith("I-5")], [])

    def test_unchanged_is_clean(self):
        self.assertEqual(self.i5(), [])

    def test_an_edited_published_file_fails_even_when_its_manifest_was_updated(self):
        run = self.domain / "runs" / "r-1"
        with open(run / "claims.jsonl", "a", encoding="utf-8") as f:
            f.write("\n")
        lines = [l for l in (run / "manifest.sha256").read_text(encoding="utf-8").splitlines() if not l.endswith("  claims.jsonl")]
        lines.append(f"{hashlib.sha256((run / 'claims.jsonl').read_bytes()).hexdigest()}  claims.jsonl")
        (run / "manifest.sha256").write_text("".join(l + "\n" for l in sorted(lines, key=lambda l: l.split("  ")[1])), encoding="utf-8")
        found = self.i5()
        self.assertIn("I-5 x.example/runs/r-1/claims.jsonl: changed since the base", found)
        self.assertIn("I-5 x.example/runs/r-1/manifest.sha256: changed since the base", found)

    def test_a_deleted_published_file_or_folder_fails(self):
        (self.domain / "runs" / "r-1" / "claims.md").unlink()
        self.assertIn("I-5 x.example/runs/r-1/claims.md: deleted since the base", self.i5())

    def test_a_file_added_to_a_published_folder_fails(self):
        (self.domain / "runs" / "r-1" / "todo.json").write_text("[]\n", encoding="utf-8")
        self.assertIn("I-5 x.example/runs/r-1/todo.json: added to a published run folder", self.i5())

    def test_a_publication_adding_one_run_passes(self):
        self.add_run("r-2", ["C-001", "C-004"], "2026-11-01T00:00:00Z", previous="r-1")
        (self.domain / "index.md").write_text((self.domain / "index.md").read_text(encoding="utf-8").replace("current_run: r-1", "current_run: r-2"),
                                              encoding="utf-8")
        with open(self.domain / "changelog.md", "a", encoding="utf-8") as f:
            f.write("2026-11-01: second run.\n")
        (self.root / "method" / "prompts").mkdir(parents=True)
        (self.root / "method" / "prompts" / f"{hashlib.sha256(b'prompt').hexdigest()}.md").write_text("prompt", encoding="utf-8")
        self.assertEqual(self.i5(publication=True), [])

    def publish_r2(self):
        self.add_run("r-2", ["C-001", "C-004"], "2026-11-01T00:00:00Z", previous="r-1")
        (self.domain / "index.md").write_text((self.domain / "index.md").read_text(encoding="utf-8").replace("current_run: r-1", "current_run: r-2"),
                                              encoding="utf-8")

    def test_a_publication_adding_a_force_added_cache_or_an_odd_prompt_fails(self):  # review4 Q1
        self.publish_r2()
        cache = self.root / "tools" / "toolkit" / "__pycache__" / "gen-evidence-page.cpython-312.pyc"
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b"not really bytecode")
        (self.root / ".gitignore").write_text("__pycache__/\ndist/\n", encoding="utf-8")
        self.git("add", ".gitignore")
        self.git("add", "-f", str(cache))
        odd = self.root / "method" / "prompts" / "sub" / "not-a-prompt.js"
        odd.parent.mkdir(parents=True)
        odd.write_text("x", encoding="utf-8")
        misnamed = self.root / "method" / "prompts" / f"{'c' * 64}.md"
        misnamed.write_text("text whose hash is not cccc", encoding="utf-8")
        found = self.i5(publication=True)
        for said in ("tools/toolkit/__pycache__/gen-evidence-page.cpython-312.pyc: not part of a publication",
                     "method/prompts/sub/not-a-prompt.js: not part of a publication",
                     f"method/prompts/{'c' * 64}.md: not named by the sha256 of its text"):
            self.assertTrue(any(said in f for f in found), (said, found))

    def test_ignored_untracked_files_do_not_count(self):
        self.publish_r2()
        (self.root / ".gitignore").write_text("__pycache__/\ndist/\n", encoding="utf-8")
        self.git("add", ".gitignore")
        self.git("commit", "-q", "-m", "ignore")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.git("reset", "-q", "--soft", "HEAD~1")  # base now includes .gitignore and the publication is unstaged
        self.git("checkout", "-q", self.base, "--", ".gitignore")
        for local in ("tools/__pycache__/x.pyc", "dist/evidence/x.html", "x.example/runs/r-1/__pycache__/y.pyc"):
            (self.root / local).parent.mkdir(parents=True, exist_ok=True)
            (self.root / local).write_bytes(b"local only")
        self.assertFalse(any("x.pyc" in f or "dist/" in f for f in self.i5(publication=True)), self.i5(publication=True))

    def test_a_force_added_file_in_a_published_run_folder_fails(self):
        (self.root / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
        cache = self.domain / "runs" / "r-1" / "__pycache__" / "y.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"x")
        self.git("add", "-f", str(cache))
        self.assertIn("I-5 x.example/runs/r-1/__pycache__/y.pyc: added to a published run folder", self.i5())

    def test_index_body_and_changelog_without_newline(self):
        index = self.domain / "index.md"
        index.write_text(index.read_text(encoding="utf-8") + "body\n", encoding="utf-8")
        (self.domain / "changelog.md").write_text("2026-10-30: first run.", encoding="utf-8")   # no newline at the end
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "body")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.publish_r2()
        index.write_text(index.read_text(encoding="utf-8").replace("body\n", "current_run: smuggled\n"), encoding="utf-8")
        with open(self.domain / "changelog.md", "a", encoding="utf-8") as f:
            f.write(" Edited.\n")
        found = self.i5(publication=True)
        self.assertIn("I-5 x.example/index.md: changes more than current_run", found)
        self.assertIn("I-5 x.example/changelog.md: not an append", found)

    def test_a_publication_touching_anything_else_fails(self):
        self.add_run("r-2", ["C-001"], "2026-11-01T00:00:00Z", previous="r-1")
        self.add_run("r-3", ["C-001"], "2026-11-02T00:00:00Z", previous="r-2")
        (self.domain / "changelog.md").write_text("rewritten\n", encoding="utf-8")
        (self.domain / "index.md").write_text((self.domain / "index.md").read_text(encoding="utf-8").replace("X Ltd", "Y Ltd"),
                                              encoding="utf-8")
        (self.root / "README.md").write_text("x\n", encoding="utf-8")
        found = self.i5(publication=True)
        for said in ("adds 2 run folders, a publication adds one", "x.example/changelog.md: not an append",
                     "x.example/index.md: changes more than current_run", "README.md: not part of a publication"):
            self.assertTrue(any(said in f for f in found), (said, found))

    def test_a_publication_must_point_current_run_at_its_new_run(self):
        self.add_run("r-2", ["C-001"], "2026-11-01T00:00:00Z", previous="r-1")
        self.assertIn("I-5 x.example/index.md: current_run is r-1, the new run is r-2", self.i5(publication=True))

    def test_a_publication_may_not_edit_an_existing_prompt(self):
        prompt = self.root / "method" / "prompts" / f"{'b' * 64}.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("v1\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "prompt")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.add_run("r-2", ["C-001"], "2026-11-01T00:00:00Z", previous="r-1")
        (self.domain / "index.md").write_text((self.domain / "index.md").read_text(encoding="utf-8").replace("current_run: r-1", "current_run: r-2"),
                                              encoding="utf-8")
        prompt.write_text("v2\n", encoding="utf-8")
        self.assertTrue(any(f"method/prompts/{'b' * 64}.md: not part of a publication" in f for f in self.i5(publication=True)))

    def test_an_unknown_base_is_reported(self):
        self.assertTrue(any(f.startswith("I-5 could not run") or f.startswith("I-5 base") for f in
                            B.check(self.root, base="no-such-ref")))

    def test_the_cli_takes_base_and_publication(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(B.main(["--root", str(self.root), "--check", "--base", self.base]), 0)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            B.main(["--root", str(self.root), "--check", "--publication"])   # needs --base


if __name__ == "__main__":
    unittest.main()
