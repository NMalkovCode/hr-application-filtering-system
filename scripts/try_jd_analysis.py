"""Developer check: run the real job-description analysis and print the proposed filters.

Usage (from the project folder):
    .venv\\Scripts\\python.exe scripts\\try_jd_analysis.py samples\\sample_job_description.txt
    .venv\\Scripts\\python.exe scripts\\try_jd_analysis.py --set-key      # store your API key once
    .venv\\Scripts\\python.exe scripts\\try_jd_analysis.py JD.docx --model claude-sonnet-5-5

The API key is read from Windows Credential Manager (the same place the app stores it).
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hr_screening import config, settings  # noqa: E402
from hr_screening.jd_analyzer import analyze_job_description, load_job_description  # noqa: E402
from hr_screening.llm import ClaudeClient, LLMError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job_description", nargs="?", type=Path)
    parser.add_argument("--model", default=config.DEFAULT_MODEL, choices=sorted(config.MODELS))
    parser.add_argument("--set-key", action="store_true", help="store your Anthropic API key and exit")
    args = parser.parse_args()

    if args.set_key:
        settings.set_api_key(getpass.getpass("Anthropic API key (input hidden): "))
        print("Saved to Windows Credential Manager.")
        return 0
    if not args.job_description:
        parser.error("give a job description file, or --set-key")

    try:
        client = ClaudeClient(settings.get_api_key() or "", model=args.model)
        filter_set = analyze_job_description(client, documents=load_job_description(args.job_description))
    except LLMError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"\n{filter_set.job_title}\n{filter_set.job_summary}\n")
    for f in filter_set.filters:
        print(f"{f.id}  [{f.type.label:9}] w{f.weight}  {f.category.label:13} {f.criterion}")
        print(f"     ↳ {f.rationale}")
    if filter_set.warnings:
        print("\nWarnings for HR:")
        for w in filter_set.warnings:
            print(f"  • {w}")
    u = client.usage
    print(f"\n{u.calls} call(s), {u.input_tokens + u.cache_read_tokens} input / {u.output_tokens} output tokens, "
          f"≈ ${u.cost_usd:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
