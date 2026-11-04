"""The CI workflow (argus-claims 02-sa-service-map §5.3): only ready pull requests into main, no push or draft runs,
every change checked (the ruleset requires `check`, so a skipped run would block a merge), a time limit, superseded runs
cancelled, read-only, checkout on Node 24, the branch name never pasted into a script. Stdlib only: read as text."""
import re
import unittest

from test_build import REPO

WORKFLOW = REPO / ".github" / "workflows" / "check.yml"


class Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.lines = [line.rstrip() for line in cls.text.splitlines()]

    def test_triggers_only_on_ready_pull_requests_into_main(self):
        on = self.text.split("\non:", 1)[1].split("\njobs:", 1)[0]
        self.assertNotIn("push", on)
        self.assertNotIn("schedule", on)
        self.assertNotIn("workflow_dispatch", on)
        self.assertIn("pull_request:", on)
        self.assertRegex(on, r"branches:\s*\[main\]")
        self.assertRegex(on, r"types:\s*\[opened, synchronize, reopened, ready_for_review\]")
        self.assertIn("github.event.pull_request.draft == false", self.text)

    def test_every_change_is_checked(self):  # a required check that never reports leaves its PR unmergeable
        on = self.text.split("\non:", 1)[1].split("\njobs:", 1)[0]
        self.assertNotRegex(on, r"\bpaths(-ignore)?:")
        self.assertNotRegex(on, r"\bbranches-ignore:")

    def test_checkout_runs_on_node_24(self):  # v4 runs on Node 20, which GitHub has deprecated
        self.assertEqual(re.findall(r"uses: actions/checkout@(\S+)", self.text), ["v5"])

    def test_limits_and_permissions(self):
        self.assertRegex(self.text, r"timeout-minutes: 10\b")
        self.assertRegex(self.text, r"cancel-in-progress: true")
        self.assertRegex(self.text, r"permissions:\s*\n\s+contents: read")

    def test_it_runs_the_tests_then_the_check_against_main(self):
        self.assertIn("fetch-depth: 0", self.text)  # I-5 needs the base commit
        tests = self.text.index("python3 -I -m unittest discover -s tools/tests")
        check = self.text.index("python3 -I tools/build.py --check --base origin/main")
        self.assertLess(tests, check)

    def test_the_branch_name_never_reaches_a_script_directly(self):
        runs = "\n".join(l for l in self.lines if not l.lstrip().startswith(("HEAD_REF:", "#")))
        self.assertNotIn("github.head_ref", runs)
        self.assertIn("HEAD_REF: ${{ github.head_ref }}", self.text)
        self.assertRegex(self.text, r'case "\$HEAD_REF" in\s*\n\s*claims/\*\)')


if __name__ == "__main__":
    unittest.main()
