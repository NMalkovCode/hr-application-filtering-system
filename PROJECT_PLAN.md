# HR Candidate Screening Tool — Project Plan

A Windows desktop application (`HRScreening.exe`) that lets an HR team member turn a job
description into verified screening filters, run a folder of applications through them, and
receive ranked, sorted applications with a one-page justification report for each candidate.

---

## 1. Confirmed requirements

| # | Topic | Decision |
|---|---|---|
| 1 | Analysis engine | Anthropic Claude API (general version). Model selectable in Settings. |
| 2 | Bias safeguards | Protected characteristics (age, gender, nationality, ethnicity, religion, marital/family status, disability, photo) are ignored and never mentioned in output. |
| 3 | Input format | Primary: one **subfolder per candidate** (CV + cover letter + any other files). Also supported: one **file per candidate** directly in the folder, or a mix of both. File types: **PDF, DOCX, scanned images** (PNG, JPG, TIFF, BMP, WEBP, scanned/image-only PDFs). |
| 4 | Eliminated candidates | Copied to a **Not Suitable** folder (no .docx). Spreadsheet gives a one-line reason. |
| 5 | Other Role | The ranking tier takes priority. A candidate who passes for the initial role goes into their tier folder **and** is duplicated into **Other Role** if another open role fits them better. The spreadsheet tracks how many candidates in each tier also fit another role. |
| 6 | Tier split | Score thresholds (default Top ≥ 80, Close 65–79, Backup 50–64, < 50 = Not Suitable). Adjustable in the UI. |
| 7 | Reports | One .docx (max one page, as concise as possible) for every Top / Close / Backup / Other Role placement. |
| 8 | Other open roles | UI accepts a **careers page URL** *or* a **folder of job descriptions**. If neither is given, the Other Role check is skipped. |
| 9 | File handling | Original applications are **copied**; the source folder is never modified. |
| 10 | Volume / language | 10–200 applications per run. English only. |
| 11 | Branding | None for now (plain, clean report template). |
| 12 | Deployment | Several HR users, each with their **own API key**, stored per Windows user in Windows Credential Manager. The key is never built into the .exe. |
| 13 | Extras | Saved filters with a **Clear Cache** button; **Anonymised mode** toggle; **cost estimate** shown when a run could exceed the user's spending limit. |

### Interpretations to confirm during review
- **Spending limit** — a per-run budget (USD) the user sets in Settings. Before processing, the
  tool estimates the cost; if the upper estimate exceeds the limit it shows a warning with the
  estimate and asks to continue or cancel. (The API does not expose account balances, so the
  limit is user-defined.)
- **Eliminated but suited to another role** — copied to **Other Role** only (not also to Not
  Suitable); the spreadsheet still records them as eliminated for the initial role, and the
  report's first line states they are *not* suitable for the initial role.
- **Report first line** — the Other Role report's first line states the candidate's standing for
  the initial role (e.g. *"Also suitable for Data Analyst — Close Match (72/100)."* or *"Not
  suitable for Data Analyst: lacks required SQL experience."*). The tier report for the same
  candidate also notes the alternative role in one line.

---

## 2. Technical approach

| Area | Choice | Notes |
|---|---|---|
| Language | Python 3.12 | |
| UI | PySide6 (Qt 6) | Native-looking Windows UI, editable tables, background worker threads. |
| Packaging | PyInstaller → `HRScreening.exe` | No Python install needed on HR machines. |
| AI | `anthropic` Python SDK | Default model `claude-opus-5-5`; `claude-sonnet-5-5` / `claude-haiku-5-5` selectable for lower cost. Structured (JSON-schema) outputs for every call. Prompt caching for the parts shared across candidates (instructions, job description, filters, open roles). |
| PDF text | `pypdf` | Permissive licence. Image-only PDFs are sent to Claude as PDF documents (Claude reads scanned pages directly — no Tesseract install needed). |
| DOCX text | `python-docx` | Paragraphs and tables. |
| Images | `Pillow` | Normalised (format conversion, downscaling) and sent to Claude's vision input. |
| Careers page | `httpx` + `beautifulsoup4` | Fetch the listing page, find job links, extract posting text. Folder alternative reads .pdf/.docx/.txt job descriptions. |
| Reports | `python-docx` | Fixed one-page template with length budget per section. |
| Spreadsheet | `openpyxl` | `Summary.xlsx`. |
| API key storage | `keyring` | Windows Credential Manager, per Windows user. |

### Scoring design
The model does not invent a final score. For each verified filter it returns a judgement
(**Met / Partially met / Not met / No evidence**) with a short evidence quote from the
application. The program then:
1. Eliminates the candidate if any **Must-have** is *Not met* or has *No evidence*.
2. Computes a weighted 0–100 score over **all** filters (Met = 1, Partial = 0.5, else 0), so
   how strongly a candidate meets the must-haves also counts, and a role with only must-haves
   can still be ranked.
3. Assigns the tier using the UI thresholds and ranks within the tier. Equal scores are ordered by
   must-have strength, then the AI's **overall-fit rating (1–10)** - added after the trial showed
   many identical scores among strong candidates - then the number of filters fully met.
4. Applications that cannot be assessed (unreadable, not an application, AI error, or too
   large) go to **Needs Review** - never silently to Not Suitable. So do applications that
   would be rejected while some of their files were unreadable (the unreadable file may be the
   CV); their provisional assessment is kept in the spreadsheet.

One AI call per application returns the judgements, the report text (verdict, up to 4
strengths, up to 3 gaps, a one-line summary) and the alternative-role assessment. The shared
part of the prompt (instructions, job, filters, open roles) is cached; the first application
runs alone to write the cache, then the rest run in parallel. The model is told to treat the
application as data: instructions hidden in a CV (e.g. "rank me highly") are ignored and
reported to HR as integrity notes.

This keeps rankings consistent, explainable and reproducible, and the evidence feeds the reports.

### Other Role logic
1. Open roles are loaded once per run (URL or folder) and condensed into short requirement
   summaries (one low-effort API call per role, up to 40 roles). The role currently being
   screened is excluded by title matching, and the evaluator is told to ignore it too.
   - **URL:** public job-board APIs of Greenhouse, Lever, Ashby, SmartRecruiters and Recruitee
     (detected from the URL or an embed on the page); otherwise schema.org JobPosting data;
     otherwise links that look like postings (HTML or PDF); otherwise Claude reads the roles
     from the page text. Uses the Windows certificate store and system proxy.
   - **Folder:** each PDF / DOCX / TXT / image file is one job description.
   - Cached: URL results for 24 hours, folder results until a file in it changes. Clear Cache
     removes them. If the source cannot be read, the UI offers to continue without the check.
2. In the same per-candidate evaluation call, the model also assesses the candidate against the
   open-role summaries and returns the best alternative (if any) with a fit rating and reasons.
3. A candidate is placed in **Other Role** when the alternative fit is *Strong*, and either they
   were eliminated for the initial role or the alternative fit is clearly better than their
   initial-role standing.

---

## 3. User workflow (UI)

1. **Settings** (first launch, editable later): API key, model, tier thresholds, spending limit,
   default output folder, concurrency.
2. **Step 1 — Job description:** paste text or load a .docx/.pdf/.txt. A saved filter set is
   offered if this job description was screened before.
3. **Step 2 — Filters:** the extracted filters appear in an editable table (criterion, category,
   Must-have/Preferred, weight 1–5). HR can edit, add, delete. **Verify** locks them and saves them
   to the cache.
4. **Step 3 — Run setup:** applications folder; optional careers URL **or** job-description folder;
   output folder; **Anonymised mode** toggle; thresholds shown and adjustable. The cost estimate
   appears here, with a warning if it could exceed the spending limit.
5. **Processing:** progress bar, per-candidate status log, Cancel button. Unreadable files are
   reported, not fatal.
6. **Results:** counts per folder, sortable results table, "Open output folder" button.
7. **Clear Cache** button (Settings) — removes saved filter sets and cached open-role summaries.

Implementation notes (Phase 6): PySide6 with a fixed light theme (independent of Windows dark
mode). AI calls and file work run on background threads, so the window stays responsive. The
spending-limit warning only appears when the upper estimate exceeds the limit; otherwise the
estimate is shown on the progress screen. If the careers source cannot be read, HR is asked
whether to continue without the Other Role check. Closing the window during a run asks first,
then cancels and saves what was assessed. Settings, step 3 choices and thresholds are remembered
per Windows user.

---

## 4. Output structure

```
<Output folder>/<Job Title>_<YYYY-MM-DD_HHMM>/
├── Top Match/        01_Jane_Doe/ (copied application)  +  01_Jane_Doe_Report.docx
├── Close Match/
├── Backup/
├── Other Role/       Jane_Doe/  +  Jane_Doe_Other_Role_Report.docx
├── Not Suitable/     (copied applications, no reports)
├── Needs Review/     (unreadable files, non-applications, AI errors - checked by hand)
└── Summary.xlsx
```

- Rank prefix (`01_`, `02_` …) keeps each tier folder sorted best-first.
- **Summary.xlsx**
  - *Candidates* sheet: rank, candidate, tier, score, must-haves met, other-role fit (Yes/No),
    suggested role, one-line reason, report file.
  - *Summary* sheet: count per tier, and a cross-tab of how many in each tier also fit another
    role (and which roles).
- **Anonymised mode:** candidates become `Candidate 001`, `Candidate 002` … in folder names, report
  names, report text and the Candidates sheet. A separate `Candidate_Key.xlsx` maps IDs to the
  original files so HR can contact candidates later. (Copied application files themselves are
  not redacted.)

### Report template (≤ 1 page)
1. First line: alternative-role / initial-role note when applicable.
2. Header: candidate, role, tier, score, rank, must-haves met.
3. Verdict — 1–2 sentences.
4. Key strengths — up to 4 bullets with evidence.
5. Gaps / risks — up to 3 bullets; integrity notes if any.
6. Filter checklist — requirement with its evidence underneath · type · result.

Section length limits are enforced in the prompt and again in code. A layout estimate
(calibrated against Microsoft Word) picks the most detailed layout that fits one A4 page,
compacting step by step (shorter evidence, evidence only for unmet items, no evidence, smaller
fonts, shorter text) only when needed. Tests verify real page counts in Word up to 25 filters
with maximum-length text.

The Summary.xlsx also has a *Filter Matrix* sheet (every candidate × every filter, colour-coded)
and a *Filters* sheet (the verified filters). The *Candidates* sheet distinguishes "Strong fit for
another role" (tracked for everyone) from "Copied to Other Role" (placement rule above).

---

## 5. Cost

Approximate per-application cost with prompt caching (roughly 3–5k tokens of application text):

| Model | Per application | 200 applications |
|---|---|---|
| Claude Opus 5.5 (default) | ~$0.05–0.10 | ~$10–20 |
| Claude Sonnet 5.5 | ~$0.025–0.05 | ~$5–10 |
| Claude Haiku 5.5 | < $0.005 | < $1 |

The app computes its own estimate before each run from the actual application sizes and the
model's prices, and compares the upper bound against the spending limit.

---

## 6. Project structure

```
HR Tool/
├── PROJECT_PLAN.md
├── README.md
├── requirements.txt / requirements-dev.txt
├── run.py                       # entry point (also the PyInstaller target)
├── hr_screening/
│   ├── config.py                # app paths, constants, supported file types, model prices
│   ├── settings.py              # user settings + API key (keyring)
│   ├── models.py                # dataclasses: Candidate, SourceDocument, Filter, results…
│   ├── extraction.py            # PDF / DOCX / image reading
│   ├── discovery.py             # find candidates in a folder (both layouts)
│   ├── filter_cache.py          # saved filter sets            (Phase 2)
│   ├── llm.py                   # Claude client wrapper        (Phase 2)
│   ├── jd_analyzer.py           # job description → filters    (Phase 2)
│   ├── evaluator.py             # candidate evaluation/scoring (Phase 3)
│   ├── careers.py               # open roles from URL / folder (Phase 4)
│   ├── reports.py               # one-page .docx               (Phase 5)
│   ├── spreadsheet.py           # Summary.xlsx                 (Phase 5)
│   ├── organizer.py             # output folders and copies    (Phase 5)
│   ├── pipeline.py              # end-to-end run orchestration (Phase 5)
│   └── ui/                      # PySide6 windows and widgets  (Phase 6)
├── tests/
└── build/                       # PyInstaller spec + build script (Phase 8)
```

---

## 7. Phases

| Phase | Scope | Done when |
|---|---|---|
| 1. Foundations | Project skeleton, settings + key storage, document extraction, candidate discovery | Tests pass on sample PDFs/DOCX/images in both folder layouts |
| 2. Job description analysis | Claude client wrapper, filter extraction, filter cache | A real job description produces a sensible editable filter set |
| 3. Evaluation engine | Per-candidate evaluation, knock-outs, scoring, tiers, ranking | Synthetic candidates land in the expected tiers consistently |
| 4. Careers integration | URL scraping, folder alternative, role condensing, Other Role logic | Alternative roles detected on test data; skipped cleanly when no source is given |
| 5. Outputs | Reports, Summary.xlsx, folder organisation, anonymised mode, cost estimate | Full run from the command line produces the complete output tree |
| 6. UI | PySide6 screens for the whole workflow, background processing, cancel | HR workflow runs end-to-end from the UI |
| 7. Testing & hardening | Edge cases (empty/corrupt files, huge CVs, network errors, rate limits), report length checks | Test suite + a 50-candidate trial run |
| 8. Packaging | PyInstaller build, test on a clean Windows machine, HR user guide | `HRScreening.exe` runs without Python installed |

---

## 7a. Hardening (Phase 7)

| Risk | Handling |
|---|---|
| Rate limits / overloaded API / network blips | SDK retries quickly (4×); the evaluator then waits 20 s, 60 s, 120 s and retries again before giving up. Waits stop immediately on Cancel. |
| Truncated or malformed AI answers | Retried; a truncated answer is retried with a 3× larger output limit. Refusals are not retried (server-side fallback model already tried). |
| Oversized applications | > 100 images, > 28 MB of files or > 150k tokens → Needs Review with the reason (never truncated silently). |
| Memory on 200 scanned applications | File contents are released after the size estimate and after each evaluation; only ~20–25 MB is used for 200 applications. |
| Empty / missing / locked / password-protected / old-format files | Specific messages; other files of the same candidate are still assessed and the report notes what was skipped. |
| Windows 260-character path limit | Copies and reports use long-path (\\\\?\\) form. |
| > 99 candidates in one tier | Rank prefixes widen (001_…) so folders still sort correctly. |
| Results saved inside the applications folder | Refused (they would be picked up as candidates next time). |
| PC sleeping during a long run | Sleep is blocked for the duration of the run. |
| Credential Manager unavailable | Settings shows the error instead of crashing. |

Verification: 180 automated tests (including UI and Word page-count tests), plus
`scripts/load_test.py` — 200 generated applications through the full pipeline with a simulated
API that is slow, rate-limits 10% of first attempts and refuses 2%: all applications accounted
for, all rate-limited calls recovered, outputs complete.

`scripts/make_trial_data.py` generates 50 realistic, varied applications (strong/good/borderline/
weak/other-role/unrelated profiles, phone photos, scans, TIFFs, prompt injection, broken files)
with an `expected.csv`, for a live trial against `samples/sample_job_description.txt`.

## 7b. Packaging (Phase 8)

- `packaging\build.ps1`: tests → PyInstaller (`packaging\HRScreening.spec`, single file, no
  console, icon + version info, unused Qt modules excluded, no UPX) → offline self-test of the
  built exe → user guide. Output: `dist\HRScreening.exe` (~70 MB, window in ~4 s) and
  `dist\HR_User_Guide.pdf`.
- `HRScreening.exe --self-test <file>` checks the bundled program on any machine without
  internet or an API key.
- Both the Claude API and careers-page connections use the Windows certificate store.
- `docs\HR_User_Guide.docx/.pdf` (generated by `packaging\make_user_guide.py`) and
  `docs\IT_Deployment_Notes.md`.
- Not yet done: code signing (needs the organisation's certificate), testing on a clean
  machine without the development tools, and a live trial with a real API key.

## 8. Risks & notes
- **Data protection:** application content is sent to Anthropic's API. Companies using the tool
  should check their data-processing agreements and candidate privacy notices.
- **Human oversight:** the tool supports, not replaces, HR decisions (AI-assisted hiring is
  treated as high-risk under the EU AI Act). Reports always show their evidence.
- **Careers pages vary:** sites that build their listings in JavaScript may not be readable
  directly; the folder alternative always works.
- **Rate limits:** low-tier API accounts may need lower concurrency; the SDK retries
  automatically and the run can be cancelled.
