#!/usr/bin/env python3
"""Record a social-profile read as a run source, from the session transcript, so no model retypes the bytes. Stdlib only.

    python3 -I record-social-source.py <run_dir> <transcript.jsonl> --platform x --profile OneDroidAI --url https://x.com/OneDroidAI

The read itself is a social_get_profile_posts call on our social-media MCP, made by the session (Michal, 1 Nov 2026: a targeted read of
a company's own public profile). This script takes the latest successful call with those exact arguments and writes:
- <run_dir>/sources/social-<platform>-<name>.json: the response, byte for byte;
- a line in <run_dir>/sources.sha256;
- an entry in <run_dir>/http-cache.json under the profile URL: status 200, sha256, bytes, the tool, its parameters and the time, all
  taken from the transcript. The harness serves that entry and never fetches the host (run.json connector_hosts).
It prints the row for the lister's source table in claims.md. Refused: a host not in connector_hosts, a LinkedIn person URL (companies
only, never people), a second read of the same source with different bytes (one read per source per run).
"""
import argparse
import hashlib
import json
import pathlib
import re
import sys
import urllib.parse

TOOL_SUFFIX = "social_get_profile_posts"


def find_read(transcript, platform, profile):
    """The latest successful call with these exact arguments: (tool, input, response text, time). None if there is none."""
    uses, found = {}, None
    with open(transcript, encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            content = (row.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for c in content:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "tool_use" and c.get("name", "").endswith(TOOL_SUFFIX):
                    args = c.get("input") or {}
                    if args.get("platform") == platform and args.get("profile") == profile:
                        uses[c["id"]] = (c["name"], args)
                elif c.get("type") == "tool_result" and c.get("tool_use_id") in uses and not c.get("is_error"):
                    body = c.get("content")
                    if isinstance(body, list) and body and isinstance(body[0], dict) and body[0].get("type") == "text":
                        name, args = uses[c["tool_use_id"]]
                        found = (name, args, body[0]["text"], row.get("timestamp"))
    return found


def refuse(msg):
    print("refused: " + msg, file=sys.stderr)
    return 2


def record(run, transcript, platform, profile, url):
    url = url.rstrip("/")
    parts = urllib.parse.urlsplit(url)
    run_json = json.loads((run / "run.json").read_text(encoding="utf-8"))
    if (parts.hostname or "").lower() not in {h.lower() for h in run_json.get("connector_hosts", [])}:
        return refuse(f"{parts.hostname} is not in run.json connector_hosts")
    if platform == "linkedin" and not parts.path.startswith("/company/"):
        return refuse("a LinkedIn source must be a /company/ page: companies only, never people")
    found = find_read(transcript, platform, profile)
    if found is None:
        return refuse(f"no successful {TOOL_SUFFIX} call for {platform} {profile} in the transcript")
    tool, args, text, when = found
    body = text.encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    name = re.sub(r"[^a-z0-9-]+", "-", parts.path.rstrip("/").rsplit("/", 1)[-1].lower()).strip("-") or "profile"
    rel = f"sources/social-{platform}-{name}.json"
    path = run / rel
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            return refuse(f"{rel} already holds a different read: one read per source per run")
        print(f"| {url} | {rel} | 200 | {len(body)} | {digest} |")
        return 0
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(body)
    with open(run / "sources.sha256", "a", encoding="utf-8") as f:
        f.write(f"{digest}  {rel}\n")
    cache_path = run / "http-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    cache[url] = {"status": 200, "sha256": digest, "bytes": len(body), "final_url": url, "via": "connector", "tool": tool,
                  "params": args, "fetched_at": when}
    cache_path.write_text(json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")
    print(f"| {url} | {rel} | 200 | {len(body)} | {digest} |")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", type=pathlib.Path)
    ap.add_argument("transcript")
    ap.add_argument("--platform", required=True)
    ap.add_argument("--profile", required=True, help="exactly as passed to the tool")
    ap.add_argument("--url", required=True, help="the profile URL the claims cite")
    a = ap.parse_args(argv)
    return record(a.run_dir, a.transcript, a.platform, a.profile, a.url)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
