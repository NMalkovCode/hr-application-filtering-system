from __future__ import annotations

import json

import httpx
import pytest

from hr_screening.web import CareersError, fetch_postings, html_to_text, normalise_url

from .conftest import make_text_pdf

LONG = "We are looking for someone to own our data pipelines. " * 10


def site(routes: dict[str, object]) -> httpx.Client:
    """httpx client whose responses come from `routes` (url -> html str, dict/list JSON,
    bytes, int status or exception). Unknown URLs return 404."""
    def handler(request: httpx.Request) -> httpx.Response:
        item = routes.get(str(request.url))
        if item is None:
            return httpx.Response(404)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, int):
            return httpx.Response(item)
        if isinstance(item, (dict, list)):
            return httpx.Response(200, json=item)
        if isinstance(item, bytes):
            return httpx.Response(200, content=item, headers={"content-type": "application/pdf"})
        return httpx.Response(200, html=item)
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def titles(result):
    return [p.title_hint for p in result.postings]


def test_greenhouse_board():
    http = site({"https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true": {"jobs": [
        {"title": "Data Engineer", "absolute_url": "https://x/1", "location": {"name": "Leeds"},
         "content": "&lt;p&gt;Build &lt;b&gt;pipelines&lt;/b&gt;&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Python&lt;/li&gt;&lt;/ul&gt;"},
    ]}})
    result = fetch_postings("https://boards.greenhouse.io/acme", http)
    assert titles(result) == ["Data Engineer"]
    text = result.postings[0].documents[0].text
    assert "Location: Leeds" in text and "Build\npipelines" in text and "• Python" in text
    assert result.notes[0] == "Found 1 role on the Greenhouse job board."


def test_empty_ats_board_falls_back_to_page():
    http = site({
        "https://api.ashbyhq.com/posting-api/job-board/acme": {"jobs": []},
        "https://jobs.ashbyhq.com/acme": f"<main><h2>Barista</h2><p>{LONG}</p></main>",
    })
    result = fetch_postings("https://jobs.ashbyhq.com/acme", http)
    assert result.postings == [] and result.page_text.startswith("Barista")


def test_lever_ashby_recruitee_smartrecruiters():
    http = site({
        "https://api.lever.co/v0/postings/acme?mode=json": [
            {"text": "Ops Manager", "hostedUrl": "u", "descriptionPlain": "Run ops",
             "lists": [{"text": "Requirements", "content": "<li>5 years</li>"}], "categories": {"location": "York"}},
        ],
        "https://api.ashbyhq.com/posting-api/job-board/acme": {"jobs": [
            {"title": "Designer", "jobUrl": "u", "descriptionPlain": "Design", "isListed": True},
            {"title": "Hidden", "jobUrl": "u", "descriptionPlain": "x", "isListed": False},
        ]},
        "https://acme.recruitee.com/api/offers/": {"offers": [
            {"title": "Accountant", "careers_url": "u", "description": "<p>Books</p>", "requirements": "<p>ACCA</p>",
             "status": "published"},
        ]},
        "https://api.smartrecruiters.com/v1/companies/acme/postings": {"content": [{"id": "9", "name": "Driver"}]},
        "https://api.smartrecruiters.com/v1/companies/acme/postings/9": {
            "postingUrl": "u", "jobAd": {"sections": {"jobDescription": {"text": "<p>Drive</p>"},
                                                      "qualifications": {"text": "<p>Licence C</p>"}}}},
    })
    assert titles(fetch_postings("https://jobs.lever.co/acme", http)) == ["Ops Manager"]
    assert "• 5 years" in fetch_postings("jobs.lever.co/acme", http).postings[0].documents[0].text
    assert titles(fetch_postings("https://jobs.ashbyhq.com/acme", http)) == ["Designer"]
    assert "ACCA" in fetch_postings("https://acme.recruitee.com", http).postings[0].documents[0].text
    assert "Licence C" in fetch_postings("https://careers.smartrecruiters.com/acme", http).postings[0].documents[0].text


def test_embedded_board_on_company_page():
    http = site({
        "https://acme.test/careers": '<html><body><iframe src="https://boards.greenhouse.io/embed/job_board?for=acme"></iframe></body></html>',
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true": {"jobs": [{"title": "Analyst", "content": "x"}]},
    })
    assert titles(fetch_postings("https://acme.test/careers", http)) == ["Analyst"]


def test_ats_failure_falls_back_to_page():
    http = site({"https://jobs.lever.co/acme": f"<main><h1>Jobs</h1><p>{LONG}</p></main>"})
    result = fetch_postings("https://jobs.lever.co/acme", http)
    assert result.postings == [] and "data pipelines" in result.page_text


def test_json_ld_job_postings():
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "Organization", "name": "Acme"},
        {"@type": "JobPosting", "title": "Nurse", "description": "&lt;p&gt;Care for patients&lt;/p&gt;",
         "qualifications": "NMC registration", "url": "https://acme.test/jobs/nurse"},
    ]}
    http = site({"https://acme.test/jobs": f'<script type="application/ld+json">{json.dumps(ld)}</script>'})
    (posting,) = fetch_postings("https://acme.test/jobs", http).postings
    assert posting.title_hint == "Nurse" and posting.source == "https://acme.test/jobs/nurse"
    assert "Care for patients" in posting.documents[0].text and "NMC registration" in posting.documents[0].text


def test_link_discovery_fetches_postings_and_skips_noise(tmp_path):
    listing = """<html><body><nav><a href="/">Home</a></nav><main>
      <a href="/careers">All jobs</a>
      <a href="/careers/data-engineer">Data Engineer</a>
      <a href="/careers/ops-manager#apply">Operations Manager</a>
      <a href="/careers/ops-manager">Operations Manager (Leeds)</a>
      <a href="/careers/data-engineer/apply">Apply now</a>
      <a href="/about">About us</a>
      <a href="https://other.test/jobs/1">Partner job</a>
      <a href="/careers/js-only">Fancy JS role</a>
      <a href="/careers/brochure.pdf">Warehouse Lead (PDF)</a>
    </main></body></html>"""
    http = site({
        "https://acme.test/careers": listing,
        "https://acme.test/careers/data-engineer": f"<main><h1>Data Engineer</h1><p>{LONG}</p></main>",
        "https://acme.test/careers/ops-manager": f"<main><h1>Ops</h1><p>{LONG}</p></main>",
        "https://acme.test/careers/js-only": '<div id="root"></div><script>app()</script>',
        "https://acme.test/careers/brochure.pdf": make_text_pdf(tmp_path / "jd.pdf", "Warehouse Lead role " * 20).read_bytes(),
    })
    result = fetch_postings("https://acme.test/careers", http)
    assert titles(result) == ["Data Engineer", "Operations Manager", "Warehouse Lead (PDF)"]
    assert result.postings[2].documents[0].name == "brochure.pdf"
    assert any("js-only" in n and "JavaScript" in n for n in result.notes)


def test_page_without_links_returns_text_for_ai_extraction():
    http = site({"https://acme.test/jobs": f"<body><header>Menu</header><h2>Barista</h2><p>{LONG}</p><footer>©</footer></body>"})
    result = fetch_postings("https://acme.test/jobs", http)
    assert result.postings == []
    assert result.page_text.startswith("Barista") and "Menu" not in result.page_text


@pytest.mark.parametrize("route, message", [
    (404, "not found"),
    (403, "refused access"),
    (500, "error \\(500\\)"),
    (httpx.ConnectError("boom"), "Could not connect"),
    (httpx.ReadTimeout("slow"), "too long"),
])
def test_http_failures(route, message):
    with pytest.raises(CareersError, match=message):
        fetch_postings("https://acme.test/jobs", site({"https://acme.test/jobs": route}))


def test_normalise_url():
    assert normalise_url(" acme.test/careers ") == "https://acme.test/careers"
    with pytest.raises(CareersError):
        normalise_url("ftp://acme.test")
    with pytest.raises(CareersError):
        normalise_url("")


def test_html_to_text():
    assert html_to_text("<p>Hello</p><ul><li>One</li><li>Two</li></ul>") == "Hello\n• One\n• Two"
