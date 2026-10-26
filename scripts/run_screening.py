"""Run a complete screening from the command line (the UI does the same steps).

    .venv\\Scripts\\python.exe scripts\\run_screening.py --jd samples\\sample_job_description.txt ^
        --apps "C:\\Applications\\Data Analyst" --out "C:\\Screening Results" ^
        [--careers-url https://example.com/careers | --careers-folder "C:\\Open Roles"] [--anonymised] [--yes]

Uses the API key, model, thresholds, spending limit and concurrency from the app's Settings.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hr_screening import filter_cache, settings as settings_mod  # noqa: E402
from hr_screening.jd_analyzer import analyze_job_description, load_job_description  # noqa: E402
from hr_screening.llm import ClaudeClient, LLMError  # noqa: E402
from hr_screening.models import Tier  # noqa: E402
from hr_screening.pipeline import RunRequest, ScreeningPipeline  # noqa: E402


def confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--jd", type=Path, required=True, help="job description file")
    p.add_argument("--apps", type=Path, required=True, help="applications folder")
    p.add_argument("--out", type=Path, help="output folder (default: Settings, else next to the applications)")
    p.add_argument("--careers-url", default="")
    p.add_argument("--careers-folder", default="")
    p.add_argument("--anonymised", action="store_true")
    p.add_argument("--yes", action="store_true", help="accept filters and cost without asking")
    args = p.parse_args()

    s = settings_mod.Settings.load()
    try:
        client = ClaudeClient(settings_mod.get_api_key() or "", model=s.model)
        jd_docs = load_job_description(args.jd)

        saved = filter_cache.find_filter_set(jd_docs)
        if saved and confirm(f"Use filters saved on {saved.saved_at:%d %b %Y %H:%M}?", args.yes):
            filter_set = saved.filter_set
        else:
            print("Analysing the job description…")
            filter_set = analyze_job_description(client, documents=jd_docs)

        print(f"\n{filter_set.job_title}")
        for f in filter_set.filters:
            print(f"  {f.id} [{f.type.label:9}] w{f.weight}  {f.criterion}")
        for w in filter_set.warnings:
            print(f"  ! {w}")
        if not confirm("\nVerify these filters?", args.yes):
            return 1
        filter_cache.save_filter_set(jd_docs, filter_set)

        request = RunRequest(
            applications_dir=args.apps,
            output_dir=args.out or Path(s.output_dir or args.apps.parent),
            filter_set=filter_set,
            thresholds=s.thresholds,
            anonymised=args.anonymised or s.anonymised_mode,
            concurrency=s.concurrency,
            careers_url=args.careers_url,
            careers_folder=args.careers_folder,
        )
        pipeline = ScreeningPipeline(client)
        prep = pipeline.prepare(request, on_status=lambda msg, *_: print(f"\r{msg:60}", end="", flush=True))
        print()
        for note in prep.roles.notes:
            print(f"  • {note}")
        print(prep.estimate.describe())
        if prep.estimate.exceeds(s.spending_limit_usd):
            print(f"WARNING: this could exceed your spending limit of ${s.spending_limit_usd:.2f}.")
        if not confirm(f"Screen {len(prep.candidates)} applications?", args.yes):
            return 1

        outcome = pipeline.run(prep, on_progress=lambda pr: print(
            f"\rAssessed {pr.done}/{pr.total} — ${pr.cost_usd:.2f}", end="", flush=True))
        print()
    except (LLMError, OSError, ValueError) as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1

    for tier in Tier:
        print(f"  {tier.value:13} {outcome.count(tier)}")
    print(f"  {'Other Role':13} {outcome.other_role_count}")
    print(f"Results: {outcome.run_dir}\nActual cost: ${outcome.cost_usd:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
