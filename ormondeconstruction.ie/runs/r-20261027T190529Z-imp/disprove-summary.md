# disprove-summary (Ormonde Construction Ltd, own surfaces only)

Refs are relative to the run directory (text/ = visible-text extracts, sources/ = saved HTML). Live checks (GET, HTTP 200): /history/, /team-2/, /one-page/, /contact/, /robots.txt, /sitemap_index.xml. No third-party sites were used. People are referred to by role.

Counts: yes 10, no 46, unverifiable 19 (75 claims).

## "yes" contradictions

### C-004 (high that the two dates disagree), and C-001, C-002 (low)
- Side A, history timeline: text/history.txt#L25 `2002`, L26 `Ormonde Construction Ltd`, L27 `has been in operation for over 21 years`. Live /history/ (200) line 1055 shows `2002`.
- Side B: text/home.txt#L58 `in operation since 2001`; text/about-company.txt#L26 `Ormonde Construction was established in 2001`; text/john.txt#L26 `set up Ormonde Construction Ltd in 2001`.
- Reconciliation: 2002 could mark incorporation or first trading year; the site never says. Hence low for C-001 and C-002. "Over 21 years" (C-003) holds under either year, so graded no.

### C-022 and C-026 (medium)
- Side A: text/paddy.txt#L26 `Commercial Director`; text/team.txt#L26 `Commercial Director`.
- Side B: text/team-2.txt#L26 `Commercial Manager` (live /team-2/ 200, line 16; dateModified 2024-09-20).
- C-026 as worded (one page listing all four titles) matches neither page: each lists three titles. Reconciliation: /team-2/ may be an older duplicate page.

### C-046 and C-047 (low)
- Side A: text/project-crokers.txt#L26 `over 88 housing units`; text/projects.txt#L27 same.
- Side B: text/residential.txt#L29-L32 Crokers Hill card `over 70 housing units`.
- Reconciliation: both are lower bounds ("over"), so both can be true; flagged because one project carries two different counts.

### C-060 (low)
- Side A: text/upcoming-projects.txt#L32 lists `Thomastown Housing` as upcoming (page dateModified 2025-09-19).
- Side B: text/new-social-and-affordable-housing-scheme-in-kilkenny.txt#L26 `Construction has started on a new social and affordable housing scheme in Thomastown` (dated 8 October 2024).
- Reconciliation: may be a different scheme or a stale list.

### C-073 (medium)
- Claim: took part in the 7 March 2024 event.
- Own page text/international-womens-day.txt#L27-L28: event `takes place on 7th March`; staff member `was part of the panel discussion at last years event`.
- Reconciliation: the post may be read as covering participation in both years; it names only the earlier event.

### C-074 (low)
- Claim: podcast feature, July 2024.
- text/quality-in-quantity.txt#L25 `July 14, 2024` (profile article, sitemap lastmod 2024-07-15) vs text/lisa-oshea-leading-the-way.txt#L25-L28 `October 8, 2024`, the podcast episode post (sitemap lastmod 2024-10-08).
- Career facts agree between the two. Reconciliation: the claim may cite the July profile article, which is not the podcast.

## Near misses not scored
- C-019: text/one-page.txt#L28 `250 +` Projects (template placeholder page, live /one-page/ 200) vs text/john.txt#L26 `over 200 projects`; 250 is over 200 and the page is lorem-ipsum template.
- C-006: footer prints `353 (0) 56 778 6940` without the plus that /contact/ has. The saved contact page hash differs from live, but address, phone and email are identical.
- C-010/C-011: about page and home sector menu omit food and beverage, sports and leisure, and nursing care that appear in the news article and bio; additive only.
- C-015: history timeline entries 2009 and 2022 repeat identical text and the order is 2002, 2009, 2020, 2006, 2014, 2022.
- C-016: 2020 history entry says `the following clients` but no client names or logos render (saved or live), so unsupported, not contradicted.
- C-044: sustainability statement `Learn More` / `Contact Us` buttons link to `#` (sources/sustainability.html#L1089-L1174).
- C-056/C-058: `Ladys Well St.` (project page) vs `Ladywell Street` (news article), spelling only.
- C-053: project URL spells `walken`, page text `Walkin`.
- C-042: two copies of the quality paragraph on the about page differ by one trailing phrase.
- C-052: Market Square text repeats Droughill paragraph wording.
- Template pages with lorem-ipsum content (home slides, core-values, faq, our-team, one-page) are live and indexed in the page sitemap; not scored against any claim.
