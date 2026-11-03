"""The deployment configuration (argus-claims 02-sa-service-map §5, §5.1): vercel.json builds the site the way the
tests do, the middleware's own tests pass under Node, and the build refuses a Python too old for it."""
import json
import shutil
import subprocess
import unittest

from test_build import B, REPO


class Deploy(unittest.TestCase):
    def test_vercel_builds_what_the_tests_build(self):
        config = json.loads((REPO / "vercel.json").read_text(encoding="utf-8"))
        self.assertEqual((config["buildCommand"], config["outputDirectory"], config["installCommand"], config["framework"]),
                         ("python3 -I tools/build.py --out dist", "dist", "", None))
        self.assertEqual((config["cleanUrls"], config["trailingSlash"]), (True, False))
        vary = {h["source"] for h in config["headers"] for x in h["headers"] if x == {"key": "Vary", "value": "Accept"}}
        self.assertEqual(vary, {"/evidence", "/evidence/:path*"})
        types = {h["source"]: x["value"] for h in config["headers"] for x in h["headers"] if x["key"] == "Content-Type"}
        self.assertEqual(types["/(.*).md"], "text/markdown; charset=utf-8")
        self.assertEqual(types["/(.*).jsonl"], "application/x-ndjson; charset=utf-8")

    def test_the_middleware_tests_pass_under_node(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "node is needed to test middleware.js")  # fails rather than skips: a skip proves nothing
        done = subprocess.run([node, "--test", str(REPO / "tools" / "tests" / "middleware.test.mjs")], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout[-2000:])
        self.assertIn("# pass 7", done.stdout)

    def test_python_version(self):
        self.assertEqual(B.MIN_PYTHON, (3, 11))
        self.assertFalse(B.python_ok((3, 9, 18)))
        self.assertFalse(B.python_ok((3, 10, 0)))
        self.assertTrue(B.python_ok((3, 11, 0)))
        self.assertTrue(B.python_ok((3, 12, 3)))


if __name__ == "__main__":
    unittest.main()
