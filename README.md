# onedroid-evidence

The public evidence pages at `https://onedroid.ai/evidence`: for each company listed, every checkable claim its own
public pages make, where it is made, and what the company itself has published that backs it. Built by Argus Claims
(`providentiaww/argus-claims`); the design is in that repo's `docs/dark-factory/`.

## Layout

```
tools/build.py                  the compiler (stdlib Python): this tree -> dist/evidence/
tools/toolkit/                  vendored from argus-claims; TOOLKIT_VERSION = "<commit> <sha256 of MANIFEST>"
tools/tests/                    the compiler's tests, the live-page goldens, landing-paths.txt
config/exclusions.json          per-domain exclusion rules = each current run's run.json exclusions
<domain>/index.md               front matter: publisher, current_run, self, split_low_confidence, certificate_url, certificate_note
<domain>/changelog.md           the page's change log, one entry per line
<domain>/runs/<run_id>/         a published run record; never edited after merge (manifest.sha256 lists every file)
```

## Build and check

```
python3 -I tools/build.py --out dist          # the site, into an empty folder
python3 -I tools/build.py --check             # two builds + the invariants I-1..I-9 (I-5 with --base <ref>)
python3 -I -m unittest discover -s tools/tests
```

A run folder holds only the published record files; source bytes are never published (hashes only).
