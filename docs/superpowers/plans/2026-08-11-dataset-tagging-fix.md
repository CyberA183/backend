# Dataset Tagging Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `backend/pythonscripts/tagdataset.py` so it writes `description_tags` as a
plain list of matched tags (not a dict of every category set true/false), stops
fetching external URLs during tagging, uses word-boundary keyword matching instead of
raw substrings, corrects the keyword taxonomy (adds a missing Wildlife & Nature
category, removes overly generic keywords that caused mistagging), and re-tags every
file in `backend/data/sources/`.

**Architecture:** Single-file script fix (`tagdataset.py`) done in three layered,
independently-testable changes — matching engine, text source, taxonomy — followed by
a data-regeneration pass over the real YAML files. No other files in the repo change.

**Tech Stack:** Python 3, `pyyaml`, `pytest` (new dev dependency for this script).

## Global Constraints

- Scope is `backend/pythonscripts/tagdataset.py` and `backend/data/sources/*.yml`
  only. Do not touch `web/backend/pythonscripts/tagdataset.py` or any file under
  `web/` — it is a separate, intentionally-diverged codebase (per design spec
  `docs/superpowers/specs/2026-08-11-dataset-tagging-design.md`).
- `description_tags` must always be written as a flat, sorted `list[str]` of matched
  tag names — never a dict, never including unmatched categories.
- No network calls anywhere in the tagging path (`build_text_blob`/`infer_tags`).
- Keyword matching requires a word boundary immediately before each keyword
  (`\b` + the keyword), not a raw substring check.
- All commands below assume the working directory is `/Users/arielthompson/Documents/CDL/backend`
  unless stated otherwise.

---

### Task 1: Matching engine — word-boundary regex, list output

**Files:**
- Modify: `pythonscripts/tagdataset.py` (`infer_tags`, ~lines 162-163; `process_file`'s
  tag-handling lines, ~lines 179-180)
- Modify: `pythonscripts/requirements.txt` (add `pytest`)
- Create: `pythonscripts/test_tagdataset.py`

**Interfaces:**
- Produces: `infer_tags(text: str) -> list[str]` — returns a sorted list of tag names
  whose category has at least one keyword matching `text` at a word boundary. Reads
  keywords from the module-level `TAG_RULES` dict (unchanged shape:
  `dict[str, list[str]]`), so later tasks can freely edit `TAG_RULES`'s contents
  without touching this function.

- [ ] **Step 1: Add `pytest` to the Python dependencies**

Edit `pythonscripts/requirements.txt` to add a line `pytest` (the file currently has no
trailing newline after `pyyaml` — add `pytest` on its own new line).

- [ ] **Step 2: Install dependencies**

Run (from `backend/`):
```bash
pip install -r pythonscripts/requirements.txt
```
Expected: installs `numpy`, `pandas`, `scipy`, `requests`, `openpyxl`, `pyyaml`,
`pytest` with no errors.

- [ ] **Step 3: Write the failing tests**

Create `pythonscripts/test_tagdataset.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tagdataset


def test_infer_tags_returns_sorted_list(monkeypatch):
    monkeypatch.setattr(tagdataset, "TAG_RULES", {
        "Beta": ["banana"],
        "Alpha": ["apple"],
    })
    result = tagdataset.infer_tags("this text mentions banana and apple")
    assert result == ["Alpha", "Beta"]
    assert isinstance(result, list)


def test_infer_tags_word_boundary_avoids_substring_match(monkeypatch):
    monkeypatch.setattr(tagdataset, "TAG_RULES", {"Meals": ["meal"]})
    assert tagdataset.infer_tags("a warm bowl of oatmeal") == []
    assert tagdataset.infer_tags("school meal programs") == ["Meals"]


def test_infer_tags_keeps_stem_prefix_matches(monkeypatch):
    monkeypatch.setattr(
        tagdataset, "TAG_RULES", {"Government Administration": ["govern"]}
    )
    assert tagdataset.infer_tags("data from the state government") == [
        "Government Administration"
    ]


def test_infer_tags_no_match_returns_empty_list(monkeypatch):
    monkeypatch.setattr(tagdataset, "TAG_RULES", {"Alpha": ["apple"]})
    assert tagdataset.infer_tags("nothing relevant here") == []
```

- [ ] **Step 4: Run the tests to verify they fail**

Run (from `backend/`):
```bash
python3 -m pytest pythonscripts/test_tagdataset.py -v
```
Expected: `test_infer_tags_returns_sorted_list` FAILS (current `infer_tags` returns a
dict of all keys true/false, not `["Alpha", "Beta"]`).
`test_infer_tags_word_boundary_avoids_substring_match` FAILS (current substring match
makes `"oatmeal"` match `"meal"`).

- [ ] **Step 5: Implement `infer_tags` with word-boundary regex**

In `pythonscripts/tagdataset.py`, replace:

```python
def infer_tags(text: str) -> dict[str, bool]:
    return {tag: any(word in text for word in keywords) for tag, keywords in TAG_RULES.items()}
```

with:

```python
def infer_tags(text: str) -> list[str]:
    matched: list[str] = []
    for tag, keywords in TAG_RULES.items():
        if any(re.search(r"\b" + re.escape(keyword), text) for keyword in keywords):
            matched.append(tag)
    return sorted(matched)
```

Then, in `process_file`, replace:

```python
    matched = [tag for tag, val in tags.items() if val]
    print(f"  - Tags matched: {matched}")
```

with:

```python
    print(f"  - Tags matched: {tags}")
```

(`tags` is now already the matched list, so no filtering step is needed. The next
line, `data["description_tags"] = tags`, is unchanged — it now assigns a list instead
of a dict.)

- [ ] **Step 6: Run the tests to verify they pass**

Run (from `backend/`):
```bash
python3 -m pytest pythonscripts/test_tagdataset.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add pythonscripts/tagdataset.py pythonscripts/requirements.txt pythonscripts/test_tagdataset.py
git commit -m "Fix dataset tagger to write matched tags as a list, not a full true/false dict"
```

---

### Task 2: Text source — drop URL fetching, use only local YAML fields

**Files:**
- Modify: `pythonscripts/tagdataset.py` (module docstring; delete `extract_urls`,
  `html_to_text`, `fetch_url_text`; rewrite `build_text_blob`; update `process_file`
  and `main` call sites; remove `import requests`)
- Modify: `pythonscripts/test_tagdataset.py` (add tests)

**Interfaces:**
- Consumes: nothing from Task 1 beyond the already-fixed `infer_tags(text: str) ->
  list[str]`.
- Produces: `build_text_blob(data: dict[str, Any]) -> str` — no `timeout` or
  `max_url_text` parameters anymore (dropped). `process_file(path: Path, dry_run:
  bool) -> None` — also drops `timeout`/`max_url_text` parameters. Task 3 will call
  `build_text_blob` and `infer_tags` with these exact signatures.

- [ ] **Step 1: Write the failing tests**

Append to `pythonscripts/test_tagdataset.py`:

```python
import inspect


def test_build_text_blob_uses_only_local_fields():
    data = {
        "title": "Test Title",
        "description": "Test description",
        "download": {"description": "CSV download"},
        "provider": {"name": "Test Agency", "agency": "Test Department"},
    }
    blob = tagdataset.build_text_blob(data)
    assert "test title" in blob
    assert "test description" in blob
    assert "csv download" in blob
    assert "test agency" in blob
    assert "test department" in blob


def test_build_text_blob_handles_missing_fields():
    assert tagdataset.build_text_blob({}) == ""


def test_tagger_has_no_network_dependency():
    source = inspect.getsource(tagdataset)
    assert "import requests" not in source
    assert "fetch_url_text" not in source
    assert "extract_urls" not in source
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`):
```bash
python3 -m pytest pythonscripts/test_tagdataset.py -v
```
Expected: `test_build_text_blob_uses_only_local_fields` FAILS with a `TypeError`
(current `build_text_blob` requires `timeout` and `max_url_text` arguments).
`test_tagger_has_no_network_dependency` FAILS (`import requests` and
`fetch_url_text` are still present).

- [ ] **Step 3: Remove URL fetching and rewrite `build_text_blob`**

In `pythonscripts/tagdataset.py`:

1. Remove the line `import requests`.

2. Delete the three functions `extract_urls`, `html_to_text`, and `fetch_url_text` in
   their entirety (the block starting at `def extract_urls(node: Any) -> list[str]:`
   through the end of `def fetch_url_text(url: str, timeout: int, max_chars: int) ->
   str:`).

3. Replace `build_text_blob`:

```python
def build_text_blob(data: dict[str, Any], timeout: int, max_url_text: int) -> str:
    parts: list[str] = []

    for key in ["title", "short_title", "description"]:
        value = data.get(key)
        if isinstance(value, str):
            parts.append(value)

    provider = data.get("provider", {})
    if isinstance(provider, dict):
        for key in ["name", "agency"]:
            value = provider.get(key)
            if isinstance(value, str):
                parts.append(value)

    for url in extract_urls(data):
        parts.append(fetch_url_text(url, timeout=timeout, max_chars=max_url_text))

    return "\n".join(parts).lower()
```

with:

```python
def build_text_blob(data: dict[str, Any]) -> str:
    parts: list[str] = []

    for key in ["title", "short_title", "description"]:
        value = data.get(key)
        if isinstance(value, str):
            parts.append(value)

    download = data.get("download", {})
    if isinstance(download, dict):
        value = download.get("description")
        if isinstance(value, str):
            parts.append(value)

    provider = data.get("provider", {})
    if isinstance(provider, dict):
        for key in ["name", "agency"]:
            value = provider.get(key)
            if isinstance(value, str):
                parts.append(value)

    return "\n".join(parts).lower()
```

4. In `process_file`, replace:

```python
def process_file(path: Path, timeout: int, max_url_text: int, dry_run: bool) -> None:
    print(f"\nProcessing: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    if not isinstance(data, dict):
        print("  - Skipped (YAML root is not an object)")
        return

    text_blob = build_text_blob(data, timeout=timeout, max_url_text=max_url_text)
    tags = infer_tags(text_blob)
```

with:

```python
def process_file(path: Path, dry_run: bool) -> None:
    print(f"\nProcessing: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    if not isinstance(data, dict):
        print("  - Skipped (YAML root is not an object)")
        return

    text_blob = build_text_blob(data)
    tags = infer_tags(text_blob)
```

5. In `main`, replace:

```python
    for path in files:
        process_file(path=path, timeout=10, max_url_text=4000, dry_run=False)
```

with:

```python
    for path in files:
        process_file(path=path, dry_run=False)
```

6. Update the module docstring at the top of the file, replacing:

```python
"""
Simple dataset tagger.

What it does:
- Reads one or more YAML files from backend/data/sources
- Uses the requests library to fetch text content from any URLs found in the YAML
- Collects text from YAML fields + URL page content
- Generates simple keyword-based description tags
- Writes tags back to each file as: description_tags: [..]

Usage:
    python tagdataset.py all
    python tagdataset.py usda-milk-production.yml
"""
```

with:

```python
"""
Simple dataset tagger.

What it does:
- Reads one or more YAML files from backend/data/sources
- Builds a text blob from each dataset's title, description, download description,
  and provider fields
- Generates simple keyword-based description tags
- Writes tags back to each file as: description_tags: [..]

Usage:
    python tagdataset.py all
    python tagdataset.py usda-milk-production.yml
"""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `backend/`):
```bash
python3 -m pytest pythonscripts/test_tagdataset.py -v
```
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pythonscripts/tagdataset.py pythonscripts/test_tagdataset.py
git commit -m "Stop fetching external URLs when tagging datasets; use local YAML fields only"
```

---

### Task 3: Taxonomy cleanup — add Wildlife & Nature, remove generic keywords, dedupe

**Files:**
- Modify: `pythonscripts/tagdataset.py` (`TAG_RULES` dict, ~lines 34-98)
- Modify: `pythonscripts/test_tagdataset.py` (add regression tests)

**Interfaces:**
- Consumes: `build_text_blob(data: dict[str, Any]) -> str` and `infer_tags(text: str)
  -> list[str]` from Tasks 1-2, unchanged.
- Produces: final `TAG_RULES` content used by Task 4's real re-tagging run.

- [ ] **Step 1: Write the failing tests**

Append to `pythonscripts/test_tagdataset.py`:

```python
def test_wildlife_category_matches_ebird_text():
    blob = tagdataset.build_text_blob({
        "title": "eBird Observation Dataset",
        "provider": {"name": "Cornell Lab of Ornithology"},
    })
    tags = tagdataset.infer_tags(blob)
    assert "Wildlife & Nature" in tags


def test_crime_data_does_not_get_energy_and_environment_tag():
    blob = tagdataset.build_text_blob({
        "title": "National FBI Crime Data Explorer",
        "provider": {
            "name": "Federal Bureau of Investigation",
            "agency": "U.S. Department of Justice",
        },
    })
    tags = tagdataset.infer_tags(blob)
    assert "Energy & Environment" not in tags
    assert "Law & Public Safety" in tags


def test_agriculture_does_not_false_positive_on_oatmeal():
    blob = tagdataset.build_text_blob({"title": "Oatmeal Recall Notices"})
    tags = tagdataset.infer_tags(blob)
    assert "Agriculture" not in tags


def test_no_duplicate_keywords_within_any_category():
    for tag, keywords in tagdataset.TAG_RULES.items():
        assert len(keywords) == len(set(keywords)), f"duplicate keyword in {tag}"


def test_generic_keywords_were_removed():
    removed = {
        "energy", "environment", "green", "efficien", "plant", "security",
        "compliance", "industry", "enterprise", "funds", "structure", "doe",
        "meal", "insect", "organic", "art", "arts", "poll",
    }
    for keywords in tagdataset.TAG_RULES.values():
        for keyword in keywords:
            assert keyword.strip() not in removed
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`):
```bash
python3 -m pytest pythonscripts/test_tagdataset.py -v
```
Expected: `test_wildlife_category_matches_ebird_text` FAILS (no `"Wildlife & Nature"`
category exists yet). `test_crime_data_does_not_get_energy_and_environment_tag` FAILS
(bare `"energy"` keyword still present, matching boilerplate-free but still generic
text). `test_generic_keywords_were_removed` and
`test_no_duplicate_keywords_within_any_category` FAIL against the current list.

- [ ] **Step 3: Replace `TAG_RULES`**

In `pythonscripts/tagdataset.py`, replace the entire `TAG_RULES` dict (from `TAG_RULES
= {` through the closing `}`) with:

```python
TAG_RULES = {
    "Agriculture": ["agricultur", "farm", "crop", "usda", "soil", "plant species", "fruit", "vegetable",
                    "livestock", "produce", "aquacultur", "poultry", "food distribut", "nutrition",
                    "plant industr", "plant ship"],
    "Business & Economy": ["business", "financial", "vendor", "commerc", "econom", "issued license",
                           "license application", "domain registration", "retail", "mobile service",
                           "storefront", "dealer", "gross receipt", "ppp loan", "bank", "insurance",
                           "gdp", "income", "wage"],
    "Children & Families": ["children", "child", "families", "foster", "visitation", "homemaker",
                            "pediatr", "parent", "mother", "father", "infant", "birth", "maternal",
                            "paternal", "family"],
    "Elections & Politics": ["election", "voter", "voting", "ballot", "campaign finance", "lobbying",
                             "lobbyist", "campaign consultant", "contributions", "legislative",
                             "congress", "representative"],
    "PreK-12 Education": ["prek", "pre-k", "k-12", "public school", "school progress", "elementary school",
                          "middle school", "high school", "school attendance", "school grounds",
                          "early learning", "private school", "school profile", "school district",
                          "all school"],
    "Energy & Environment": ["epa", "air quality", "pollution", "emission", "asbestos", "fuel", "habitat",
                             "recycling", "electricity", "tree", "conservation", "hazard zone", "sea level",
                             "flood risk", "weather", "gas", "water bod", "bodies of water",
                             "energy consumption", "soil", "canopy", "flood hazard", "water quality",
                             "rainfall", "water protection"],
    "Government Administration": ["govern", "administration", "agency", "city employ", "budget", "contractor",
                                  "revenue", "spending", "contract opportunit", "investments", "bonds",
                                  "bid opportunit", "tax", "audited financial", "annual financial report",
                                  "city department", "civil service", "mayor", "expenditure", "legislative",
                                  "congress", "representative", "department of state", "secretary of state",
                                  "treasury", "state pension", "city pension", "municipalit", "public asset",
                                  "agency and department", "department name"],
    "Health & Social Services": ["health", "cdc", "disease", "covid", "hospital", "death", "vaccin",
                                 "resilienc", "overdose", "fatality", "injury", "substance use", "rodent",
                                 "pest", "case count", "animal", "dog", "medic", "snap", "immunization",
                                 "birth", "mortality rate", "infant", "ambulatory", "acute care",
                                 "acute-care", "virus", "viral", "social service", "mosquito", "poison",
                                 "syndrom", "mold", "blood", "naloxone", "patient", "nutrition", "disabled",
                                 "senior", "assisted living", "long-term care", "care facilit"],
    "Higher Education": ["higher education", "college", "university", "postsecondary", "post-secondary",
                         "post secondary", "campus", "state school", "undergraduate", "technical school",
                         "technical institution", "career institution", "career and technical", "scholar",
                         "tuition", "admissions"],
    "Historic Preservation": ["historic", "preservation", "heritage", "landmark", "endangered building"],
    "Housing & Buildings": ["building", "permits", "vacant", "house", "housing", "elevation", "dwelling",
                            "unit preapproval", "propert", "eviction", "assessor", "plumbing",
                            "inspection complaint", "code enforcement", "rent", "landlord", "fire inspection",
                            "fire violation", "development permit", "condominium", "electrical inspection",
                            "housing code", "zoning", "community development", "housing development",
                            "architect", "homeless", "unhoused", "homeowner", "mortgage", "occupancy",
                            "encampment", "land use", "foreclos", "construct"],
    "Labor & Workforce Development": ["labor", "workforce", "employment", "unemployment", "job", "jobs",
                                      "workplace", "worker", "coops", "apprenticeship", "pension", "career",
                                      "occupation", "wage", "hour compliance"],
    "Law & Public Safety": ["legal", "crime", "public safety", "fbi", "arrest", "offense", "police",
                            "violence", "victim", "fire station", "homicide", "casualt", "offender",
                            "internal affairs", "involved officer", "officer-involved", "enforcement",
                            "dispatch", "injur", "district attorney", "sheriff", "jail", "prison", "bookings",
                            "graffiti", "fatality", "collision", "prostitut", "service incident",
                            "calls for service", "drug", "assault", "marijuana", "cannabis", "burglar",
                            "resistance", "trafficking", "carcera", "corrections", "homeland", "ethics",
                            "traffic stop", "parole", "gun", "patrol", "crash"],
    "Parks & Recreation": ["parks", "recreation", "trail", "greenway", "playground", "park district",
                           "forest preserve", "park facilit", "swimming pool", "public pool", "park building",
                           "fishing lake", "film", "parklet", "librar", "public art", "entertainment", "dog",
                           "activities", "play area", "zoo", "zoos", "touris"],
    "Population Data": ["population", "census", "acs", "demographic", "household", "poverty", "ethnicity",
                        "race", "gender", "birth", "mortality rate", "income", "gdp"],
    "Public Utilities": ["utility", "utilities", "electric", "water utility", "natural gas", "plumbing",
                         "public bathroom", "public restroom", "city facilit", "pavement", "paving", "curb",
                         "public water", "water fountain", "public works", "water quality", "trash",
                         "tree removal", "street tree", "tree recycling", "storm drain", "streetlight",
                         "main break", "parcel", "sewer", "wastewater", "waste collect", "broadband",
                         "connectivity"],
    "Restaurant and Food Service": ["restaurant", "food service", "food", "dining", "full-service",
                                    "liquor license", "serve alcohol", "bars"],
    "Transportation": ["transportation", "transit", "traffic", "road", "highway", "bridge", "vehicle",
                       "streets", "trips", "rail", "bus", "congestion", "parking", "ridership", "pedestrian",
                       "bicycle", "bike", "cyclist", "light camera", "taxi", "scooter", "sidewalk", "commuter",
                       "street closure", "speed limit", "traveled", "motor", "stops", "right of way",
                       "right-of-way", "pavement", "paving", "intersection", "cab", "cabs", "airport",
                       "passenger", "commute", "air cargo", "airplane", "flight", "lanes", "striping", "walk",
                       "walking", "railroad", "park ride", "park and ride", "truck", "rest area", "aviation",
                       "crash", "collision"],
    "Wildlife & Nature": ["bird", "wildlife", "species", "ebird", "ornitholog", "habitat", "biodiversity",
                          "observation", "flora", "fauna"],
}
```

Note: while porting this, the original `Transportation` list had a bug —
`"cab " "cabs "` (two adjacent string literals with a missing comma, which Python
silently concatenates into one string `"cab cabs "`). The replacement above fixes this
as two separate keywords, `"cab"` and `"cabs"`.

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `backend/`):
```bash
python3 -m pytest pythonscripts/test_tagdataset.py -v
```
Expected: all 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pythonscripts/tagdataset.py pythonscripts/test_tagdataset.py
git commit -m "Add Wildlife & Nature category and remove overly generic tagging keywords"
```

---

### Task 4: Re-tag real data files

**Files:**
- Modify: `data/sources/*.yml` (all 15 files, `description_tags` field only, via the
  script — not hand-edited)

**Interfaces:**
- Consumes: the finished `tagdataset.py` from Tasks 1-3 (`main()` entry point,
  unchanged CLI: `python tagdataset.py all`).

- [ ] **Step 1: Run the tagger against all source files**

Run (from `backend/`):
```bash
python3 pythonscripts/tagdataset.py all
```
Expected: prints `Processing: ...` and `Tags matched: [...]` for each of the 15 files
in `data/sources/`, then `Updated file` for each, with no errors or tracebacks.

- [ ] **Step 2: Verify every file now has list-shaped `description_tags`**

Run (from `backend/`):
```bash
python3 -c "
import yaml
from pathlib import Path

for path in sorted(Path('data/sources').glob('*.yml')):
    data = yaml.safe_load(path.open())
    tags = data.get('description_tags')
    assert isinstance(tags, list), f'{path}: description_tags is {type(tags)}, not list'
    print(path.name, '->', tags)
"
```
Expected: every line prints a Python list (e.g. `['Agriculture', 'Business & Economy',
...]`), no `AssertionError`.

- [ ] **Step 3: Spot-check the specific datasets discussed during design**

Confirm by reading the printed output from Step 2:
- `ebird-observation-dataset.yml` includes `"Wildlife & Nature"`.
- `ebird-state-summaries.yml` includes `"Wildlife & Nature"`.
- `fbi-crime-data-explorer.yml` includes `"Law & Public Safety"` and does **not**
  include `"Energy & Environment"`.
- `fbi-state-agency-data.yml` includes `"Law & Public Safety"`.
- `usda-milk-production.yml` includes `"Agriculture"`.
- `epa-tri-dioxin.yml` and `epa-airtoxscreen-county.yml` include
  `"Energy & Environment"` (this one is legitimately environmental data, unlike the
  FBI/crime files — it should still match).

If any of these don't hold, stop and re-examine the relevant `TAG_RULES` entry from
Task 3 before proceeding — do not hand-edit the YAML files to force a result.

- [ ] **Step 4: Commit the regenerated data**

```bash
git add data/sources/*.yml
git commit -m "Re-tag all datasets with corrected tagging tool"
```
