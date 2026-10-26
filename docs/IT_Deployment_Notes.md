# HR Candidate Screening — notes for IT

## What to distribute
| File | Purpose |
|---|---|
| `HRScreening.exe` (~70 MB) | The program. Single file, no installer, no admin rights needed. |
| `HR_User_Guide.pdf` | Guide for HR users. |

Copy both to each user's machine or a shared folder. Updating = replacing the exe; settings are kept.

## Requirements
- Windows 10 or 11 (64-bit). Nothing else to install.
- Each HR user needs their **own Anthropic API key** (created in the Anthropic Console under your
  organisation). Never share one key between users; keys are not built into the exe.

## Where things are stored (per Windows user)
| What | Where |
|---|---|
| API key | Windows Credential Manager → Generic credential `HRScreeningTool.AnthropicAPIKey` |
| Settings | `%APPDATA%\HRScreeningTool\settings.json` |
| Saved filters, cached open roles | `%APPDATA%\HRScreeningTool\cache\` (removed by *Clear Cache*) |
| Log | `%APPDATA%\HRScreeningTool\logs\hr_screening.log` (no application content is logged) |
| Screening results | Wherever the user chooses — they contain personal data. |

To remove completely: delete the exe, the `%APPDATA%\HRScreeningTool` folder and the credential.

## Network
Outbound HTTPS (443) only:
- `api.anthropic.com` — required.
- The company careers site, if users enter its URL, and these hiring-platform APIs when used:
  `boards-api.greenhouse.io`, `api.lever.co`, `api.eu.lever.co`, `api.ashbyhq.com`,
  `api.smartrecruiters.com`, `*.recruitee.com`.

The program uses the **Windows certificate store** (works with TLS-inspecting proxies whose root
certificate is deployed) and honours the standard `HTTPS_PROXY` / `NO_PROXY` environment variables.

## SmartScreen and antivirus
The exe is not code-signed, so Windows SmartScreen may warn on first run and some antivirus products
flag single-file Python executables. Recommended before wide rollout:
1. Sign the exe with your organisation's code-signing certificate, e.g.
   `signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a HRScreening.exe`
2. If your endpoint protection still flags it, allow-list the file hash.

## Checking a machine
`HRScreening.exe --self-test C:\Temp\selftest.txt` runs offline checks (document reading, a full
screening with a stand-in AI, Word/Excel output, credential store, network setup, user interface)
and writes the result to the file. Exit code 0 = all passed. No API key or internet needed.

## Data protection
Application content (CVs, cover letters) is sent to Anthropic's API for assessment. Before use,
confirm with your data protection officer that this is covered by your agreements with Anthropic
and by your candidate privacy notice, and review the API organisation's data-retention settings.
The tool is decision support: HR reviews every outcome.

## Rebuilding from source
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
powershell -ExecutionPolicy Bypass -File packaging\build.ps1    # tests → exe → self-test
```
Output: `dist\HRScreening.exe` and `dist\HR_User_Guide.pdf`.
