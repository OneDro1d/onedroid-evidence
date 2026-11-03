#!/usr/bin/env python3
"""Embed a claims-register fragment (gen-evidence-page.py --fragment) into a page.

    python3 -I embed-fragment.py <target.html> <fragment.html>

Replaces everything from the line containing `<!-- claims-register:start` through the line containing
`<!-- claims-register:end -->` (inclusive) with the fragment; with no markers, inserts the fragment immediately before the
first line that starts with `</main>`. Exit 2 when there are no markers and no such line (or the markers are unpaired).
Idempotent: embedding the same fragment twice gives the same bytes. The target is written only when it changed.
Prints one JSON line: target, changed, bytes_before, bytes_after.
"""
import json
import pathlib
import sys

START = "<!-- claims-register:start"
END = "<!-- claims-register:end -->"


class EmbedError(Exception):
    pass


def embed(target_text, fragment_text):
    frag = fragment_text if fragment_text.endswith("\n") else fragment_text + "\n"
    lines = target_text.splitlines(keepends=True)
    s = next((i for i, ln in enumerate(lines) if START in ln), None)
    if s is not None:
        t = next((i for i in range(s, len(lines)) if END in lines[i]), None)
        if t is None:
            raise EmbedError("start marker without end marker")
        return "".join(lines[:s]) + frag + "".join(lines[t + 1:])
    m = next((i for i, ln in enumerate(lines) if ln.startswith("</main>")), None)
    if m is None:
        raise EmbedError("no claims-register markers and no line starting with </main>")
    return "".join(lines[:m]) + frag + "".join(lines[m:])


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: embed-fragment.py <target.html> <fragment.html>", file=sys.stderr)
        return 2
    target, fragment = pathlib.Path(argv[0]), pathlib.Path(argv[1])
    before = target.read_bytes()
    try:
        new = embed(before.decode("utf-8"), fragment.read_text(encoding="utf-8")).encode("utf-8")
    except EmbedError as ex:
        print(f"embed-fragment: {ex}", file=sys.stderr)
        return 2
    changed = new != before
    if changed:
        target.write_bytes(new)
    print(json.dumps({"target": str(target), "changed": changed, "bytes_before": len(before), "bytes_after": len(new)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
