# Dataset Tagging Fix — Design

Date: 2026-08-11
Scope: `backend/pythonscripts/tagdataset.py` and `backend/data/sources/*.yml` only.
Out of scope: `web/backend/pythonscripts/tagdataset.py` — a separate, already-diverged
"starter" copy embedded in the `web` Astro project, with its own taxonomy. Not touched
by this change.

## Problem

`tagdataset.py`'s `infer_tags()` returns a `dict[str, bool]` covering all 18 categories
in `TAG_RULES`, and the full dict (true *and* false entries) is written to
`description_tags` in every source YAML file. This contradicts the script's own
docstring, which says it writes `description_tags: [..]` (a list). Downstream code
(`lib/sourceFromSqlite.mjs`, `web/src/lib/api/backend.ts`) already treats a plain list
as the intended/clean shape and only tolerates the dict form as legacy fallback — so a
list is the correct target format, not a new invention.

Beyond the format bug, the current data is also substantively wrong:

- **Stale category names.** Some on-disk `description_tags` use category names
  (`Business & Finance`, `Economy`, `Election`) that no longer exist in the current
  `TAG_RULES` (`Business & Economy`, `Elections & Politics`) — the rules were edited
  without ever re-running the tagger.
- **Missing category.** There is no wildlife/nature category, so `eBird` datasets
  (about bird observations) get every tag set to `false` — not "no topic," just
  unmodeled.
- **False positives from page-fetch noise.** `build_text_blob()` fetches every URL
  found in the YAML (agency homepage, download link, etc.) via `requests` and
  keyword-matches the raw HTML text. This pulls in unrelated nav/footer/boilerplate
  content. Concretely, both FBI crime data and EPA dioxin data currently get
  `Energy & Environment: true`, which does not match either dataset's actual subject —
  most likely a stray "energy," "green," or "efficient" from page boilerplate.
- **Overly generic keywords cause false positives even from clean text**, e.g. bare
  `energy`, `environment`, `security`, `compliance`, `industry`, `plant`, `green`,
  `efficien`, `art`, `doe` are common enough in unrelated prose to fire spuriously.
- **Substring (not word) matching** compounds the above — e.g. `meal` matches inside
  `oatmeal`, `poll` matches inside `pollution` (mitigated today only by ad hoc leading/
  trailing space padding on some, not all, keywords).
- **Duplicate keywords** within the same category list (e.g. `zoning` listed twice
  under Housing & Buildings; `ballot` listed twice under Elections & Politics).

## Fix

### 1. Output format

`infer_tags(text: str) -> list[str]` returns only the matched tag names, sorted.
`process_file()` writes `data["description_tags"] = tags` as that list. No dict, no
false entries.

### 2. Text source (drop URL fetching)

Remove `fetch_url_text()`, `html_to_text()`, `extract_urls()`, and the `requests`
dependency from the matching path entirely. `build_text_blob()` builds its text solely
from fields already present in the YAML: `title`, `short_title`, `description`,
`download.description`, `provider.name`, `provider.agency`. No network calls during
tagging — faster, deterministic, and removes the page-boilerplate noise source.

### 3. Matching engine

Replace `any(word in text for word in keywords)` (raw substring) with a regex using a
leading word boundary before each keyword: `\b` + `re.escape(keyword)`. This:

- Preserves the existing deliberate stemming design (`govern` still matches
  `government`/`governor`/`governance`; `agricultur` still matches
  `agriculture`/`agricultural`).
- Eliminates mid-word false matches like `meal` inside `oatmeal` (no word boundary
  exists between `t` and `m`).
- Makes the manual leading/trailing space padding used today (`" tax"`, `"produce "`)
  unnecessary; those keywords lose their padding and gain the same protection
  uniformly.

The leading boundary alone resolves both cases raised during design review: `meal`
no longer matches inside `oatmeal`, and `poll` no longer matches inside `pollution`
(neither has a word boundary immediately before the keyword substring). Keywords that
remain ambiguous even as whole-word matches — e.g. bare `art`, which legitimately
starts words like `article` and `artist` — are removed instead of patched (see
taxonomy cleanup below).

### 4. Taxonomy cleanup

Add one category and prune generic/ambiguous keywords, category by category:

- **New: "Wildlife & Nature"** — `bird`, `wildlife`, `species`, `ebird`, `ornitholog`,
  `habitat`, `biodiversity`, `observation`, `flora`, `fauna`. (Overlap with `habitat`
  already in Energy & Environment is intentional — a wildlife habitat dataset can
  reasonably carry both tags.)
- **Remove as too generic/ambiguous to be a reliable signal on their own:**
  `energy`, `environment`, `green`, `efficien`, `plant`, `security`, `compliance`,
  `industry`, `enterprise`, `funds`, `structure`, `doe`, `meal`, `insect`, `organic`,
  `art`, `arts`, `poll` (bare). Where a category still needs the concept, a more
  specific phrase already exists or is added (e.g. `energy consumption`, `public art`,
  `hazard zone` remain; `Energy & Environment` relies on its many specific terms —
  `epa`, `air quality`, `pollution`, `emission`, `recycling`, `water quality`, etc. —
  rather than the bare word `environment`).
- **De-duplicate** exact repeated keywords within a single category's list (e.g.
  `zoning`, `ballot`). Cross-category overlap is left as-is where it reflects a real
  multi-topic dataset (e.g. `crash`/`collision` in both Transportation and
  Law & Public Safety; `birth` in Children & Families, Health & Social Services, and
  Population Data).

Exact final keyword lists are finalized during implementation following these rules;
this doc fixes the rules and the specific removals/additions above, not a
character-for-character dict.

### 5. Re-tagging existing data

After the script is fixed, run `python tagdataset.py all` against all files in
`backend/data/sources/` so on-disk `description_tags` reflect the corrected list-based
output and corrected taxonomy. This replaces every existing `description_tags` block
(dict form, stale names) with the new list form.

### 6. Testing

Add `backend/pythonscripts/test_tagdataset.py` (pytest) covering:

- Word-boundary matching: a text containing "oatmeal" does not trigger any tag whose
  keyword is a plain substring of it; a text containing "government" still matches the
  `govern` stem.
- `infer_tags()` returns a plain sorted list, never a dict.
- Two real-world regression cases: eBird-style text (bird/species/observation) includes
  `"Wildlife & Nature"`; FBI-crime-style text (crime/arrest/offense, no environmental
  terms) does **not** include `"Energy & Environment"`.

Then run the updated tagger for real against `backend/data/sources/` and spot-check a
handful of files (eBird, FBI crime, EPA dioxin, USDA milk) by eye.

## Non-goals

- No change to `web/backend`'s copy of the tagger or its taxonomy.
- No change to the SQLite import path (`import_sources_to_sqlite.py`,
  `sourceFromSqlite.mjs`) — both already handle a list-shaped `description_tags`
  correctly today; re-running the importer after re-tagging is a normal part of the
  existing documented workflow (per `backend/README.md`), not a code change.
- No change to the other `*_tags` blocks (`anova_tags`, `association_tags`, etc.) —
  those are genuine boolean diagnostic flags by design, not a matched/unmatched tag
  list, and are out of scope for this fix.
