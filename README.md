# HR Candidate Screening Tool

Desktop tool that screens a folder of job applications against a verified set of filters derived
from a job description, sorts candidates into Top Match / Close Match / Backup / Other Role /
Not Suitable, and writes a one-page .docx justification per candidate.

See [PROJECT_PLAN.md](PROJECT_PLAN.md) for requirements, design and phases.

## Development setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

## Building the exe

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Runs the tests, builds `dist\HRScreening.exe` (single file, ~70 MB), runs the exe's offline
self-test (`HRScreening.exe --self-test report.txt`) and writes `dist\HR_User_Guide.pdf`.
Distribution notes for IT (storage locations, network, code signing): `docs\IT_Deployment_Notes.md`.

## Running the app (development)

```powershell
.\.venv\Scripts\python.exe run.py
```

On first launch the Settings dialog asks for your Anthropic API key. Screenshots of every
screen are in `docs\screenshots`. The app writes a log to
`%APPDATA%\HRScreeningTool\logs\hr_screening.log` (no application content is logged).

## Trying the job-description analysis

```powershell
.\.venv\Scripts\python.exe scripts\try_jd_analysis.py --set-key
.\.venv\Scripts\python.exe scripts\try_jd_analysis.py samples\sample_job_description.txt
```

## Running a full screening from the command line

```powershell
.\.venv\Scripts\python.exe scripts\run_screening.py --jd samples\sample_job_description.txt --apps "C:\Applications" --out "C:\Screening Results"
```

Optional: `--careers-url <url>` or `--careers-folder <folder>`, `--anonymised`, `--yes`.
An example of the output (made-up candidates) is in `samples\demo_output`
(regenerate with `scripts\make_demo_output.py`).

## Trial data and load test

```powershell
# 50 synthetic applications + open roles + expected outcomes (samples\trial_data)
.\.venv\Scripts\python.exe scripts\make_trial_data.py
# Full pipeline over 200 generated applications with a simulated, unreliable API (no cost)
.\.venv\Scripts\python.exe scripts\load_test.py
```

For a live trial, run the app with `samples\sample_job_description.txt`, applications folder
`samples\trial_data\applications` and job description folder `samples\trial_data\open_roles`,
then compare the results with `samples\trial_data\expected.csv`.

## Status

- [x] Phase 1 — foundations (settings, API key storage, document extraction, candidate discovery)
- [x] Phase 2 — job description analysis (filters, saved filter sets)
- [x] Phase 3 — evaluation engine (judgements, knock-outs, scoring, tiers, ranking, parallel runs)
- [x] Phase 4 — careers integration (careers URL / job description folder, role summaries, cache)
- [x] Phase 5 — outputs (one-page reports, Summary.xlsx, folders, anonymised mode, cost estimate, CLI)
- [x] Phase 6 — UI (five-step workflow, Settings with Clear Cache, background processing, cancel)
- [x] Phase 7 — testing & hardening (retries, memory, file edge cases, long paths, load test, trial data)
      — live trial with a real API key still to do
- [x] Phase 8 — packaging (single-file exe, icon, self-test, HR user guide, IT notes)
