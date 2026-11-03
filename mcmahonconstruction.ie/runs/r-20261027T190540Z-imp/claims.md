# McMahon Construction: claims extracted from its own public site

Fetched 2026-10-27 (UTC) with curl, browser User-Agent, no JavaScript. Extraction only; no claim is judged here.

## Sources

| source URL | local file | HTTP | bytes | sha256 |
|---|---|---|---|---|
| https://www.mcmahonconstruction.ie/ | sources/home.html | 200 | 68108 | 8c0c89c5b728c2d40679a7939c9693bfd0076f7216fc814005a0c039c78398bb |
| https://www.mcmahonconstruction.ie/sitemap.xml | sources/sitemap.xml | 200 (redirected to https://www.mcmahonconstruction.ie/sitemap_index.xml) | 976 | 897dcb142a317098ea7c612a0fe9d051e179978006d4c084cbc406c6e7b4b8ca |
| https://www.mcmahonconstruction.ie/robots.txt | sources/robots.txt | 200 | 184 | 76ec6e5a3430915fbc0b92c7e41e7665a2f6ef9e49005070adac85131b61c8a0 |
| https://www.mcmahonconstruction.ie/page-sitemap.xml | sources/page-sitemap.xml | 200 | 13711 | 827f227e4f53af0007a9216dac52d4a646ea42ced6712bf98e2b39391c906526 |
| https://www.mcmahonconstruction.ie/post-sitemap.xml | sources/post-sitemap.xml | 200 | 751 | 89522366139ce4ef35471f08877c46c89cf9ba19cfbd80eac2727b6f39cc1d45 |
| https://www.mcmahonconstruction.ie/category-sitemap.xml | sources/category-sitemap.xml | 200 | 762 | a4a76db7780c9b11ce06ad17e6bb09de8e182e21f86f972075d70fa42d6377c8 |
| https://www.mcmahonconstruction.ie/author-sitemap.xml | sources/author-sitemap.xml | 200 | 755 | bc169290b9adced73153d9d5dc32c8ece620b3b731146dd953497d5d6cefb1f3 |
| https://www.mcmahonconstruction.ie/attachment-sitemap.xml | sources/attachment-sitemap.xml | 200 | 15273 | c9607894e711d5c160ca568a6b83f298a4eb7a111393f040413870b44e99b927 |
| https://www.mcmahonconstruction.ie/about-us/ | sources/about-us.html | 200 | 69206 | 048cef54103f03b11b0c7261459c6ff85c9faf70ce27133c7a91721fa4177538 |
| https://www.mcmahonconstruction.ie/portfolio/ | sources/portfolio.html | 200 | 69638 | d4b1410ed5709209b7d6c7c1a988078e12a54ce9e7fbe439e98cc51cda70c12a |
| https://www.mcmahonconstruction.ie/our-values/ | sources/our-values.html | 200 | 68633 | de56c2fd757293ba05083beb6b9340c12e79880c6101406f926fb36aa7f4a280 |
| https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ | sources/air-tightness-and-insulation.html | 200 | 73402 | d8fb5b7953fbb7170ec4368e570e3a38d57d41e8ce8fe8bd13b0cdf09e014fba |
| https://www.mcmahonconstruction.ie/services/ | sources/services.html | 200 | 68626 | fca4c42db01f0f53d563dc285f4a7fdb129792718fb75b1693ba9eb6f83b576f |
| https://www.mcmahonconstruction.ie/photo-gallery/ | sources/photo-gallery.html | 200 | 91089 | a182af9a20386d92e8f503787c89b0ecb7830b717fae342f6a40a010c5b89942 |
| https://www.mcmahonconstruction.ie/photo-gallery/commercial/ | sources/photo-gallery_commercial.html | 200 | 74239 | 74c98d0f0f239cfb326baa9f077833046d8a451a1fe77343136a777046bb0724 |
| https://www.mcmahonconstruction.ie/hello-world/ | sources/hello-world.html | 200 | 76066 | e47e79938c698bc1c39c9b16efedba2a12daefd7b934c6331436076c52b68908 |
| https://www.mcmahonconstruction.ie/category/uncategorised/ | sources/category_uncategorised.html | 200 | 67916 | 6841853fff634c7fa1c1aaf9ab0f2ac58458bbf78c873bb240aa465b6812119c |
| https://www.mcmahonconstruction.ie/author/mccadmin/ | sources/author_mccadmin.html | 200 | 68835 | b0010e5e64f58fc18389c1627a77d19855d421afa02cf316f2209540537dc3bb |

Notes on sources:

- The page-sitemap lists 8 pages (all fetched: /, /about-us/, /portfolio/, /our-values/, /photo-gallery/, /photo-gallery/commercial/, /air-tightness-and-insulation/, /services/). The post, category and author sitemaps add /hello-world/, /category/uncategorised/, /author/mccadmin/ (all fetched).
- /hello-world/ is a 2016 post titled 'Hacked By <third party>' (site defacement from 2016-12/2017-02, still public). It carries no company claims and none are extracted from it. /category/uncategorised/ and /author/mccadmin/ only list that post.
- The attachment-sitemap lists 103 media files (images); they were not individually fetched (images, no text). The sitemap itself is hashed above.
- robots.txt contains only Yoast boilerplate (Disallow: empty, Sitemap line); no claims.
- Services page and the homepage text are the only places with a stated service list and the 35-year figure respectively. JSON-LD blocks are generic WebPage/WebSite schema.org (name, description, dates); they add no claims beyond the site description (C-004).
- Not found anywhere on the site (absence, not claims): founding year, CIRI / Safe-T-Cert / ISO / SEAI / CIF / HomeBond / insurance / company registration number, awards, guarantees, named clients, staff counts, and any project dates.
- Individual persons' names are omitted from claim text per brief.

## Claims

| id | claim | source URL(s) and locator | kind | checkability |
|---|---|---|---|---|
| C-001 | Burnchurch, Cuffesgrange, Co Kilkenny (company address) | https://www.mcmahonconstruction.ie/ (header/footer address line)<br>https://www.mcmahonconstruction.ie/about-us/ (header/footer address line)<br>https://www.mcmahonconstruction.ie/portfolio/ (header/footer address line)<br>https://www.mcmahonconstruction.ie/our-values/ (header/footer address line)<br>https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (header/footer address line)<br>https://www.mcmahonconstruction.ie/services/ (header/footer address line)<br>https://www.mcmahonconstruction.ie/photo-gallery/ (header/footer address line)<br>https://www.mcmahonconstruction.ie/photo-gallery/commercial/ (header/footer address line) | status | B |
| C-002 | 087 238 2347 (company telephone number) | https://www.mcmahonconstruction.ie/ (header/footer contact line)<br>https://www.mcmahonconstruction.ie/about-us/ (header/footer contact line)<br>https://www.mcmahonconstruction.ie/portfolio/ (header/footer contact line)<br>https://www.mcmahonconstruction.ie/our-values/ (header/footer contact line)<br>https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (header/footer contact line)<br>https://www.mcmahonconstruction.ie/services/ (header/footer contact line)<br>https://www.mcmahonconstruction.ie/photo-gallery/ (header/footer contact line)<br>https://www.mcmahonconstruction.ie/photo-gallery/commercial/ (header/footer contact line) | status | A |
| C-003 | mcmahonconstruction@icloud.com (company e-mail address) | https://www.mcmahonconstruction.ie/ (footer mailto link)<br>https://www.mcmahonconstruction.ie/about-us/ (footer mailto link)<br>https://www.mcmahonconstruction.ie/portfolio/ (footer mailto link)<br>https://www.mcmahonconstruction.ie/our-values/ (footer mailto link)<br>https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (footer mailto link)<br>https://www.mcmahonconstruction.ie/services/ (footer mailto link)<br>https://www.mcmahonconstruction.ie/photo-gallery/ (footer mailto link)<br>https://www.mcmahonconstruction.ie/photo-gallery/commercial/ (footer mailto link) | status | A |
| C-004 | A construction firm, building houses, renovations & extensions. | https://www.mcmahonconstruction.ie/ (Welcome to McMahon Construction, first paragraph; meta og:description; JSON-LD WebSite description)<br>https://www.mcmahonconstruction.ie/about-us/ (JSON-LD WebSite description) | capability | A |
| C-005 | The firm involves [two named principals, a pair of McMahons] carrying on expertise and work ethic learned from their site experience. | https://www.mcmahonconstruction.ie/ (Welcome paragraph; meta og:description) | status | B |
| C-006 | The principals have site experience of over the last 35 years. | https://www.mcmahonconstruction.ie/ (Welcome paragraph 'over the last 35 years'; meta og:description) | number | B |
| C-007 | Mc Mahon Construction is based in Kilkenny and conducts most of its business in Kilkenny & surrounding counties. | https://www.mcmahonconstruction.ie/about-us/ (Location; meta og:description) | capability | B |
| C-008 | We as a company value the need for training, in order to keep one step ahead of new regulations and building practices. | https://www.mcmahonconstruction.ie/about-us/ (Training; meta og:description) | conduct | B |
| C-009 | We have used a number of air to water heat pump units. | https://www.mcmahonconstruction.ie/about-us/ (Green Energy) | capability | B |
| C-010 | We have worked with various green insulation such as sheep's wool and wood fibre insulation etc. | https://www.mcmahonconstruction.ie/about-us/ (Green Energy) | capability | B |
| C-011 | All waste is disposed of appropriately by a licensed haulier. | https://www.mcmahonconstruction.ie/about-us/ (Waste Management) | licence | B |
| C-012 | Efforts are made to recycle material wherever possible. | https://www.mcmahonconstruction.ie/about-us/ (Waste Management) | conduct | B |
| C-013 | We enforce a clean site rule, for efficient work practice & safety on site. Each sub contractor must also adhere to this policy. | https://www.mcmahonconstruction.ie/about-us/ (Waste Management, second paragraph) | process | B |
| C-014 | We are a building firm that specialize in architecturally designed houses that have a strong attention to detail. | https://www.mcmahonconstruction.ie/portfolio/ (Private Houses; meta og:description) | capability | B |
| C-015 | We have worked with a number of the architects in the south east. | https://www.mcmahonconstruction.ie/portfolio/ (Private Houses) | number | B |
| C-016 | We have carried out a number of renovations of older houses and cottages. | https://www.mcmahonconstruction.ie/portfolio/ (Renovations) | capability | B |
| C-017 | We have been able to replaster in the traditional lime renders, replace and make good to existing stonework, salvage roofs in poor condition and bring them back to their former glory. | https://www.mcmahonconstruction.ie/portfolio/ (Renovations) | capability | B |
| C-018 | We have refurbished offices, so that they meet the needs of clients. | https://www.mcmahonconstruction.ie/portfolio/ (Refurbishments) | capability | B |
| C-019 | We use the most up to date telecommunications networks & energy efficient lighting, heating and ventilation systems [in office refurbishments]. | https://www.mcmahonconstruction.ie/portfolio/ (Refurbishments) | process | B |
| C-020 | We have been involved in a number of conservation projects. | https://www.mcmahonconstruction.ie/portfolio/ (Conservation) | capability | B |
| C-021 | Conservation project: Roth House Kilkenny, first phase to the Third House. | https://www.mcmahonconstruction.ie/portfolio/ (Conservation) | number | B |
| C-022 | Conservation project: Callan Church internal works. | https://www.mcmahonconstruction.ie/portfolio/ (Conservation) | number | B |
| C-023 | Conservation project: Coolmore House Thomastown. | https://www.mcmahonconstruction.ie/portfolio/ (Conservation) | number | B |
| C-024 | We have professional trades men as part of our team, who have plenty of experience in using traditional building methods involving stone work, lime rendering, natural slates & lead work, panelling etc. | https://www.mcmahonconstruction.ie/portfolio/ (Conservation, second paragraph) | capability | B |
| C-025 | Many of our sub contractors have worked with us for 10 years or more. | https://www.mcmahonconstruction.ie/our-values/ (Our Values, first paragraph; meta og:description) | number | B |
| C-026 | Services supplied: new builds. | https://www.mcmahonconstruction.ie/services/ (We supply the following services; meta og:description) | capability | A |
| C-027 | Services supplied: extensions & refurbishments of houses. | https://www.mcmahonconstruction.ie/services/ (We supply the following services; meta og:description) | capability | A |
| C-028 | Services supplied: carpentry, including first fix (floor joists, partitions, roofing). | https://www.mcmahonconstruction.ie/services/ (Carpentry / First fix) | capability | A |
| C-029 | Services supplied: second fix (hanging doors, fitting door frames, lock sets, skirting/architrave, wall panelling). | https://www.mcmahonconstruction.ie/services/ (Second fix) | capability | A |
| C-030 | Services supplied: maintenance to houses and commercial buildings. | https://www.mcmahonconstruction.ie/services/ (last list item) | capability | A |
| C-031 | The company has a Commercial photo gallery (and a Residential gallery) of its work. | https://www.mcmahonconstruction.ie/ (Galleries menu: Residential, Commercial)<br>https://www.mcmahonconstruction.ie/photo-gallery/commercial/ (Commercial gallery page, photos)<br>https://www.mcmahonconstruction.ie/photo-gallery/ (Gallery page, photos) | capability | A |
| C-032 | We keep up to date with the latest in heating & energy requirements as part L of the Building regulations & best practice in the different energy heating. | https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (Energy efficient house, paragraph 'We as a construction firm have a keen interest in this area') | conduct | B |
| C-033 | Having a proven track record in airtightness to buildings, insulation methods, heat recovery units & the various heating pack for houses i.e. PV panels, air to water heat pumps, oil/gas. We have experience with all of these areas. | https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (Energy efficient house; Heat pack ('Having experience with all of the heat packs we can advise')) | capability | B |
| C-034 | We have an electrical contractor who has worked with us on various projects over the last 10 years. | https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (Electrical) | number | B |
| C-035 | Our [electrical] contractor can advise at drawing stage of a lighting layout (mood lighting, levels of light, dimmers, security lights, intercom, surround sound, lighting and socket layouts). | https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (Electrical) | capability | B |
| C-036 | We are approved installers of SIGA airtight membranes and tapes. | https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (Air tightness) | licence | B |
| C-037 | We have been on training courses to up skill our team in [air tightness]. | https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (Air tightness) | process | B |
| C-038 | We have achieved an airtightness test level of 0.753 m3/(h.m2) @ 50 Pa on new concrete block built house. | https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (Air tightness) | number | B |
| C-039 | The current building regulations (Technical Guidance Documents part L) have a maximum upper limit of 5 m3/(h.m2) @ 50 Pa. | https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (Air tightness) | comparison | B |
| C-040 | Best practice in domestic dwellings calls for an ac/h rate of not more than 3.0 (natural ventilation), 1.5 (mechanical ventilation, HRU), 0.6 (passive house standard). | https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (Air tightness, ac/h list) | number | B |
| C-041 | SIGA are world leaders in air tightness to buildings. | https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (Air tightness) | comparison | C |
| C-042 | U valves [sic] of 0.15 W/m2 can be achieved to external walls or lower if required; equally low levels of .013 to attic and floors at affordable prices. | https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (Insulation) | number | B |
| C-043 | We have being [sic] involved with all of these types of [wall insulation] construction (cavity, cavity with thermal board, timber frame with cellulose, timber frame with block outer skin) and can provide our opinions. | https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (Insulation) | capability | B |
| C-044 | We have used [heat recovery] units on a number of projects. | https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (Heat recovery units) | capability | B |
| C-045 | Heat recovery units (HRU) become efficient when an air tightness of less than 1.5 ac/h is achieved. | https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (Heat recovery units) | number | B |
| C-046 | A BER rating goes from A1 most efficient to E least efficient. | https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (BER certificates) | number | B |
| C-047 | The BER covers energy use for space heating, water heating, ventilation & lighting, and is calculated on the basis of a standard occupancy using a DEAP calculation. | https://www.mcmahonconstruction.ie/air-tightness-and-insulation/ (BER certificates) | process | B |
