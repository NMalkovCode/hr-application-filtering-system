from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from hr_screening import careers
from hr_screening.careers import (
    PAGE_SYSTEM, _PageRole, _PageRoles, _RoleSummary, is_same_role, load_open_roles, normalise_title,
)
from hr_screening.llm import ClaudeClient, RateLimited
from hr_screening.web import CareersError

from .conftest import make_docx
from .fakes import fake_message, install_fake
from .test_web import LONG, site


def summarising_client(fail_on: str = "") -> tuple[ClaudeClient, list]:
    """Fake Claude: titles each posting from its first line; 'Team page' is not a posting."""
    client = ClaudeClient("sk-test")

    def respond(kwargs):
        text = "\n".join(b.get("text", "") for b in kwargs["messages"][0]["content"])
        first = text.split(">\n", 1)[-1].splitlines()[0].strip()
        if fail_on and fail_on in text:
            return RateLimited("rate limited")
        return fake_message(_RoleSummary(is_job_posting="Team page" not in text, title=first,
                                         summary=f"Summary of {first}"))
    return client, install_fake(client, respond)


def careers_site():
    return site({
        "https://acme.test/careers": """<main>
            <a href="/careers/1">Senior Data Analyst (Leeds)</a>
            <a href="/careers/2">Data Engineer</a>
            <a href="/careers/3">Data Engineer - Remote</a>
            <a href="/careers/team">Meet the team</a></main>""",
        "https://acme.test/careers/1": f"<main>Senior Data Analyst - Leeds\n<p>{LONG}</p></main>",
        "https://acme.test/careers/2": f"<main>Data Engineer\n<p>{LONG}</p></main>",
        "https://acme.test/careers/3": f"<main>Data Engineer\n<p>{LONG}</p></main>",
        "https://acme.test/careers/team": f"<main>Team page\n<p>{LONG}</p></main>",
    })


def test_no_source_skips_other_role_check():
    result = load_open_roles(None)
    assert not result.enabled and result.roles == [] and "skipped" in result.notes[0]


def test_url_roles_condensed_deduped_and_screened_role_excluded(tmp_path: Path):
    client, calls = summarising_client()
    result = load_open_roles(client, url="acme.test/careers", exclude_title="Senior Data Analyst",
                             http=careers_site(), cache_base=tmp_path)

    assert [(r.role_id, r.title) for r in result.roles] == [("R01", "Data Engineer")]
    assert result.roles[0].summary == "Summary of Data Engineer"
    assert result.roles[0].source == "https://acme.test/careers/2"
    assert any("Excluded the role being screened" in n for n in result.notes)
    assert len(calls) == 4 and all(c["output_config"] == {"effort": "low"} for c in calls)


def test_url_results_are_cached_then_expire(tmp_path: Path):
    client, calls = summarising_client()
    load_open_roles(client, url="https://acme.test/careers", http=careers_site(), cache_base=tmp_path)
    first_calls = len(calls)

    again = load_open_roles(client, url="https://ACME.test/careers/", http=site({}), cache_base=tmp_path)
    assert again.from_cache and len(calls) == first_calls
    # Exclusion is applied after the cache, so a different screened role still works.
    assert [r.title for r in again.roles] == ["Senior Data Analyst (Leeds)", "Data Engineer"]

    (cache_file,) = (tmp_path / "roles").glob("*.json")
    raw = json.loads(cache_file.read_text())
    raw["saved_at"] = time.time() - careers.URL_CACHE_SECONDS - 1
    cache_file.write_text(json.dumps(raw))
    refreshed = load_open_roles(client, url="https://acme.test/careers", http=careers_site(), cache_base=tmp_path)
    assert not refreshed.from_cache and len(calls) == first_calls * 2


def test_folder_source(tmp_path: Path):
    folder = tmp_path / "jds"
    folder.mkdir()
    make_docx(folder / "warehouse.docx", text="Warehouse Supervisor\nRun the night shift team", header="")
    (folder / "accountant.txt").write_text("Management Accountant\nACCA qualified", encoding="utf-8")
    (folder / "broken.pdf").write_bytes(b"nope")
    (folder / "~$warehouse.docx").write_bytes(b"lock")

    client, calls = summarising_client()
    result = load_open_roles(client, folder=folder, cache_base=tmp_path / "cache")
    assert result.source == "folder"
    assert sorted(r.title for r in result.roles) == ["Management Accountant", "Warehouse Supervisor"]
    assert any("broken.pdf" in n for n in result.notes)

    # Cached while the folder is unchanged; re-read when a file is added.
    assert load_open_roles(client, folder=folder, cache_base=tmp_path / "cache").from_cache
    (folder / "chef.txt").write_text("Head Chef\nRun the kitchen", encoding="utf-8")
    os.utime(folder / "chef.txt")
    updated = load_open_roles(client, folder=folder, cache_base=tmp_path / "cache")
    assert not updated.from_cache and len(updated.roles) == 3


def test_missing_folder():
    with pytest.raises(CareersError, match="not found"):
        load_open_roles(ClaudeClient("sk-test"), folder="C:/no/such/folder")


def test_page_text_fallback_extracts_roles(tmp_path: Path):
    client = ClaudeClient("sk-test")
    calls = install_fake(client, [fake_message(_PageRoles(roles=[_PageRole(title="Barista", summary="Coffee")]))])
    http = site({"https://cafe.test/jobs": f"<main><h2>Barista</h2><p>{LONG}</p></main>"})
    result = load_open_roles(client, url="https://cafe.test/jobs", http=http, cache_base=tmp_path)
    assert [r.title for r in result.roles] == ["Barista"]
    assert calls[0]["system"][0]["text"] == PAGE_SYSTEM


def test_one_failed_summary_is_noted_not_fatal(tmp_path: Path):
    client, _ = summarising_client(fail_on="careers/2")
    result = load_open_roles(client, url="https://acme.test/careers", http=careers_site(), cache_base=tmp_path)
    # /careers/2 failed, but the same role is still found via /careers/3.
    assert "data engineer" in [normalise_title(r.title) for r in result.roles]
    assert any("rate limited" in n for n in result.notes)


def test_nothing_found_explains_javascript(tmp_path: Path):
    client = ClaudeClient("sk-test")
    install_fake(client, [fake_message(_PageRoles(roles=[]))])
    http = site({"https://spa.test/jobs": f"<main><p>{LONG}</p></main>"})
    result = load_open_roles(client, url="https://spa.test/jobs", http=http, cache_base=tmp_path)
    assert result.roles == [] and "JavaScript" in result.notes[-1]


@pytest.mark.parametrize("a, b, same", [
    ("Senior Data Analyst", "Senior Data Analyst (Leeds) - Hybrid", True),
    ("Senior Data Analyst", "senior data analyst | Ref 123", True),
    ("Data Analyst", "Senior Data Analyst", False),
    ("Data Analyst", "Data Engineer", False),
    ("C++ Developer", "C# Developer", False),
])
def test_same_role_matching(a, b, same):
    assert is_same_role(a, b) is same


def test_dedupe_keeps_titles_that_normalise_to_nothing():
    from hr_screening.models import OpenRole
    roles = [OpenRole("", "(Leeds)", "x"), OpenRole("", "Data Engineer", "y"), OpenRole("", "Data Engineer - Remote", "z")]
    assert [r.title for r in careers._dedupe(roles)] == ["(Leeds)", "Data Engineer"]


def test_normalise_title():
    assert normalise_title("Senior Data Analyst (Leeds) – Hybrid") == "senior data analyst"
