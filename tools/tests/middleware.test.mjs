// Tests for middleware.js (argus-claims 02-sa-service-map §5.1): node --test tools/tests/middleware.test.mjs
// middleware.js is an ES module the way Vercel compiles it; the repo has no package.json, so it is loaded from a copy.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const copy = join(mkdtempSync(join(tmpdir(), "evidence-mw-")), "middleware.mjs");
writeFileSync(copy, readFileSync(join(here, "..", "..", "middleware.js")));
const { default: middleware, config } = await import(pathToFileURL(copy));

const BROWSER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8";

function call(path, accept) {
  const headers = accept === undefined ? {} : { accept };
  return middleware(new Request(`https://onedroid-evidence.vercel.app${path}`, { headers }));
}

function rewritten(response) {
  const target = response.headers.get("x-middleware-rewrite");
  return target === null ? null : new URL(target).pathname;
}

test("the Node.js runtime, matching /evidence and below only", () => {
  assert.equal(config.runtime, "nodejs");
  assert.deepEqual(config.matcher, ["/evidence", "/evidence/:path*"]);
});

test("Markdown asked for: the page's twin, with Vary", () => {
  for (const [path, twin] of [["/evidence/mcmahonconstruction.ie", "/evidence/mcmahonconstruction.ie.md"],
                              ["/evidence", "/evidence/index.md"], ["/evidence/", "/evidence/index.md"],
                              ["/evidence/x.example/runs", "/evidence/x.example/runs.md"],
                              ["/evidence/x.example/C-001", "/evidence/x.example/C-001.md"]]) {
    const r = call(path, "text/markdown");
    assert.equal(rewritten(r), twin, path);
    assert.equal(r.headers.get("vary"), "Accept");
    assert.equal(r.headers.get("x-middleware-next"), null);
  }
});

test("JSON asked for, without HTML: the .json twin; with HTML: the page", () => {
  assert.equal(rewritten(call("/evidence/x.example", "application/json")), "/evidence/x.example.json");
  assert.equal(rewritten(call("/evidence", "Application/JSON")), "/evidence/index.json");
  assert.equal(rewritten(call("/evidence/x.example", "text/html, application/json")), null);
});

test("Markdown wins when both are asked for", () => {
  assert.equal(rewritten(call("/evidence/x.example", "application/json, text/markdown")), "/evidence/x.example.md");
});

test("browsers, no Accept, and any user-agent pass through to the HTML", () => {
  for (const accept of [BROWSER, undefined, "*/*", ""]) {
    const r = call("/evidence/x.example", accept);
    assert.equal(r.headers.get("x-middleware-next"), "1", String(accept));
    assert.equal(rewritten(r), null);
  }
  const bot = middleware(new Request("https://onedroid-evidence.vercel.app/evidence/x.example",
    { headers: { "user-agent": "ClaudeBot/1.0", accept: BROWSER } }));
  assert.equal(rewritten(bot), null);
});

test("twins, record files and agent surfaces are served as they are", () => {
  for (const path of ["/evidence/x.example.md", "/evidence/x.example.json", "/evidence/x.example.jsonl",
                      "/evidence/x.example.html", "/evidence/llms.txt", "/evidence/sitemap.xml",
                      "/evidence/x.example/runs/r-1/manifest.sha256", "/evidence/x.example/runs/r-1/claims.md",
                      "/evidence/x.example/runs/r-1/run.json"]) {
    const r = call(path, "text/markdown");
    assert.equal(r.headers.get("x-middleware-next"), "1", path);
    assert.equal(rewritten(r), null, path);
  }
});

test("paths outside /evidence pass through", () => {
  for (const path of ["/", "/evidencex", "/argus"]) {
    assert.equal(rewritten(call(path, "text/markdown")), null, path);
  }
});
