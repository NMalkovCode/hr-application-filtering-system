"""Fetching job postings from a company's careers page.

Order of strategies:
1. Known hiring platforms with public JSON job-board APIs (Greenhouse, Lever, Ashby,
   SmartRecruiters, Recruitee), detected from the URL or from an embed on the page.
2. schema.org JobPosting data (JSON-LD) on the page - common on company sites.
3. Links on the page that look like individual postings, each fetched and read.
4. Otherwise the page text itself, from which Claude extracts any roles (see careers.py).
"""

from __future__ import annotations

import html
import json
import logging
import re
import ssl
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urldefrag, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .extraction import ExtractionError, extract_document
from .models import ContentKind, SourceDocument

log = logging.getLogger(__name__)

USER_AGENT = "HRScreeningTool/0.1 (+careers page reader)"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
MAX_POSTING_CHARS = 40_000     # job posts longer than this are page boilerplate, not content
MAX_PAGE_BYTES = 8_000_000

_JOB_PATH_HINT = re.compile(
    r"(job|career|position|vacanc|opening|role|opportunit|posting|stelle|offre|empleo)", re.I
)
_SKIP_PATH = re.compile(r"(apply|login|sign-?in|register|privacy|cookie|terms|benefit|faq|blog|news)", re.I)
_SKIP_EXT = re.compile(r"\.(png|jpe?g|gif|svg|webp|css|js|zip|docx?|xlsx?|pptx?|mp4|mp3)$", re.I)


class CareersError(Exception):
    """The careers page could not be read. The message is shown to HR."""


@dataclass
class RawPosting:
    title_hint: str
    source: str                         # URL or file path
    documents: list[SourceDocument] = field(default_factory=list)


@dataclass
class FetchResult:
    postings: list[RawPosting] = field(default_factory=list)
    # Listing page text, when no individual postings were found (roles may be listed inline).
    page_text: str = ""
    notes: list[str] = field(default_factory=list)


def make_http_client() -> httpx.Client:
    """HTTP client using the Windows certificate store (works behind corporate TLS inspection)
    and the system proxy settings."""
    try:
        import truststore
        verify: ssl.SSLContext | bool = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # pragma: no cover - fall back to certifi bundle
        verify = True
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
        timeout=TIMEOUT, follow_redirects=True, verify=verify,
    )


def fetch_postings(url: str, http: httpx.Client, max_postings: int = 40) -> FetchResult:
    url = normalise_url(url)

    for detector in _ATS_DETECTORS:
        api = detector(url)
        if api:
            result = _try_ats(api, http, max_postings)
            if result:
                return result

    page = _get(http, url)
    soup = BeautifulSoup(page.text, "html.parser")

    # A careers page may embed a hiring platform's board.
    for embedded in _embedded_board_urls(soup, url):
        for detector in _ATS_DETECTORS:
            api = detector(embedded)
            if api and (result := _try_ats(api, http, max_postings)):
                return result

    postings = _json_ld_postings(soup, url)
    if postings:
        return _capped(postings, max_postings)

    links = _posting_links(soup, url)
    result = FetchResult()
    for title, link in links[:max_postings]:
        try:
            result.postings.append(_fetch_posting_page(http, link, title))
        except CareersError as exc:
            result.notes.append(f"Skipped {link}: {exc}")
    if len(links) > max_postings:
        result.notes.append(f"Only the first {max_postings} of {len(links)} job links were read.")
    if not result.postings:
        result.page_text = page_text(soup)
    return result


def normalise_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise CareersError("No careers page URL was given.")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise CareersError(f"'{url}' is not a valid web address.")
    return url


# --- HTTP --------------------------------------------------------------------------

def _get(http: httpx.Client, url: str) -> httpx.Response:
    try:
        response = http.get(url)
    except httpx.TimeoutException as exc:
        raise CareersError("The careers page took too long to respond.") from exc
    except httpx.HTTPError as exc:
        raise CareersError(f"Could not connect to {urlparse(url).netloc} ({type(exc).__name__}).") from exc
    if response.status_code == 404:
        raise CareersError("Page not found (404). Check the URL.")
    if response.status_code in (401, 403):
        raise CareersError("The website refused access to the page. Use the job description folder instead.")
    if response.status_code >= 400:
        raise CareersError(f"The website returned an error ({response.status_code}).")
    if len(response.content) > MAX_PAGE_BYTES:
        raise CareersError("The page is too large to read.")
    return response


def _get_json(http: httpx.Client, url: str):
    response = _get(http, url)
    try:
        return response.json()
    except ValueError as exc:
        raise CareersError("Unexpected response from the hiring platform.") from exc


# --- hiring platforms (ATS) --------------------------------------------------------

@dataclass(frozen=True)
class _AtsApi:
    platform: str
    company: str
    host: str = ""


def _path_parts(url: str) -> list[str]:
    return [p for p in urlparse(url).path.split("/") if p]


def _detect_greenhouse(url: str) -> _AtsApi | None:
    p = urlparse(url)
    if p.netloc.endswith("greenhouse.io"):
        parts = _path_parts(url)
        token = (parse_qs(p.query).get("for") or [""])[0] or (parts[0] if parts and parts[0] != "embed" else "")
        return _AtsApi("greenhouse", token) if token else None
    return None


def _detect_lever(url: str) -> _AtsApi | None:
    p = urlparse(url)
    if p.netloc in ("jobs.lever.co", "jobs.eu.lever.co") and _path_parts(url):
        host = "api.eu.lever.co" if ".eu." in p.netloc else "api.lever.co"
        return _AtsApi("lever", _path_parts(url)[0], host)
    return None


def _detect_ashby(url: str) -> _AtsApi | None:
    if urlparse(url).netloc == "jobs.ashbyhq.com" and _path_parts(url):
        return _AtsApi("ashby", _path_parts(url)[0])
    return None


def _detect_smartrecruiters(url: str) -> _AtsApi | None:
    if urlparse(url).netloc in ("careers.smartrecruiters.com", "jobs.smartrecruiters.com") and _path_parts(url):
        return _AtsApi("smartrecruiters", _path_parts(url)[0])
    return None


def _detect_recruitee(url: str) -> _AtsApi | None:
    host = urlparse(url).netloc
    if host.endswith(".recruitee.com"):
        return _AtsApi("recruitee", host.split(".")[0], host)
    return None


_ATS_DETECTORS = (_detect_greenhouse, _detect_lever, _detect_ashby, _detect_smartrecruiters, _detect_recruitee)


def _try_ats(api: _AtsApi, http: httpx.Client, max_postings: int) -> FetchResult | None:
    """Read a hiring platform's public job board. None if it fails (fall back to scraping)."""
    try:
        postings = _ATS_READERS[api.platform](api, http, max_postings)
    except (CareersError, KeyError, TypeError, AttributeError) as exc:
        log.info("%s job board for '%s' not readable: %s", api.platform, api.company, exc)
        return None
    if not postings:
        return None  # wrong board name, or an empty board: try the page itself
    result = _capped(postings, max_postings)
    plural = "" if len(postings) == 1 else "s"
    result.notes.insert(0, f"Found {len(postings)} role{plural} on the {api.platform.capitalize()} job board.")
    return result


def _read_greenhouse(api, http, _max):
    data = _get_json(http, f"https://boards-api.greenhouse.io/v1/boards/{api.company}/jobs?content=true")
    return [
        _posting(j["title"], j.get("absolute_url", ""), html_to_text(html.unescape(j.get("content", ""))),
                 location=(j.get("location") or {}).get("name", ""))
        for j in data["jobs"]
    ]


def _read_lever(api, http, _max):
    data = _get_json(http, f"https://{api.host}/v0/postings/{api.company}?mode=json")
    postings = []
    for j in data:
        sections = [j.get("descriptionPlain", "")]
        for lst in j.get("lists", []):
            sections.append(f"{lst.get('text', '')}\n{html_to_text(lst.get('content', ''))}")
        sections.append(j.get("additionalPlain", ""))
        postings.append(_posting(j["text"], j.get("hostedUrl", ""), "\n\n".join(s for s in sections if s),
                                 location=(j.get("categories") or {}).get("location", "")))
    return postings


def _read_ashby(api, http, _max):
    data = _get_json(http, f"https://api.ashbyhq.com/posting-api/job-board/{api.company}")
    return [
        _posting(j["title"], j.get("jobUrl", ""), j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", "")),
                 location=j.get("location", ""))
        for j in data["jobs"] if j.get("isListed", True)
    ]


def _read_smartrecruiters(api, http, max_postings):
    base = f"https://api.smartrecruiters.com/v1/companies/{api.company}/postings"
    listing = _get_json(http, base)["content"]
    postings = []
    for j in listing[:max_postings]:
        detail = _get_json(http, f"{base}/{j['id']}")
        sections = (detail.get("jobAd") or {}).get("sections") or {}
        text = "\n\n".join(html_to_text((sections.get(k) or {}).get("text", ""))
                           for k in ("jobDescription", "qualifications", "additionalInformation"))
        postings.append(_posting(j["name"], detail.get("postingUrl", ""), text,
                                 location=(j.get("location") or {}).get("city", "")))
    return postings


def _read_recruitee(api, http, _max):
    data = _get_json(http, f"https://{api.host}/api/offers/")
    return [
        _posting(j["title"], j.get("careers_url", ""),
                 html_to_text(j.get("description", "")) + "\n\n" + html_to_text(j.get("requirements", "")),
                 location=j.get("location", ""))
        for j in data["offers"] if j.get("status", "published") == "published"
    ]


_ATS_READERS = {
    "greenhouse": _read_greenhouse,
    "lever": _read_lever,
    "ashby": _read_ashby,
    "smartrecruiters": _read_smartrecruiters,
    "recruitee": _read_recruitee,
}


def _embedded_board_urls(soup: BeautifulSoup, base_url: str) -> list[str]:
    urls = []
    for tag in soup.find_all(["iframe", "script", "a"]):
        src = tag.get("src") or tag.get("href") or ""
        if any(h in src for h in ("greenhouse.io", "lever.co", "ashbyhq.com", "smartrecruiters.com", "recruitee.com")):
            urls.append(urljoin(base_url, src))
    return list(dict.fromkeys(urls))


# --- schema.org JobPosting ---------------------------------------------------------

def _json_ld_postings(soup: BeautifulSoup, page_url: str) -> list[RawPosting]:
    postings = []
    for item in _json_ld_items(soup):
        if "JobPosting" not in _as_list(item.get("@type")):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        description = html_to_text(html.unescape(str(item.get("description") or "")))
        extra = []
        for key in ("qualifications", "skills", "experienceRequirements", "educationRequirements", "responsibilities"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                extra.append(html_to_text(value))
        if title and description:
            postings.append(_posting(title, str(item.get("url") or page_url), "\n\n".join([description, *extra])))
    return postings


def _json_ld_items(soup: BeautifulSoup) -> list[dict]:
    items: list[dict] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop(0)
            if isinstance(node, dict):
                items.append(node)
                stack.extend(_as_list(node.get("@graph")))
                stack.extend(_as_list(node.get("itemListElement")))
                if isinstance(node.get("item"), dict):
                    stack.append(node["item"])
    return items


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# --- generic link discovery --------------------------------------------------------

def _posting_links(soup: BeautifulSoup, page_url: str) -> list[tuple[str, str]]:
    """(anchor text, absolute URL) for links that look like individual job postings."""
    page = urlparse(page_url)
    site = page.netloc.removeprefix("www.")
    page_path = page.path.rstrip("/")
    found: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href, _ = urldefrag(urljoin(page_url, a["href"]))
        target = urlparse(href)
        if target.scheme not in ("http", "https") or not target.netloc.removeprefix("www.").endswith(site):
            continue
        path = target.path.rstrip("/")
        text = " ".join(a.get_text(" ", strip=True).split())
        if (
            path == page_path
            or page_path.startswith(path)          # parent pages / home
            or not _JOB_PATH_HINT.search(path)
            or _SKIP_PATH.search(path)
            or _SKIP_EXT.search(path)
            or not 3 <= len(text) <= 150
        ):
            continue
        found.setdefault(href, text)
    return [(text, url) for url, text in found.items()]


def _fetch_posting_page(http: httpx.Client, url: str, title_hint: str) -> RawPosting:
    response = _get(http, url)
    content_type = response.headers.get("content-type", "")
    if "pdf" in content_type or url.lower().endswith(".pdf"):
        return RawPosting(title_hint, url, _pdf_documents(response.content, url))
    soup = BeautifulSoup(response.text, "html.parser")
    ld = _json_ld_postings(soup, url)
    if ld:
        return ld[0]
    text = page_text(soup)
    if len(text) < 200:
        raise CareersError("page has almost no text (it may need JavaScript to display)")
    return _posting(title_hint, url, text)


def _pdf_documents(data: bytes, url: str) -> list[SourceDocument]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "posting.pdf"
        path.write_bytes(data)
        try:
            docs = extract_document(path)
        except ExtractionError as exc:
            raise CareersError(str(exc)) from exc
    name = Path(urlparse(url).path).name or "posting.pdf"
    for d in docs:
        d.path = Path(name)
    return docs


# --- text helpers ------------------------------------------------------------------

def html_to_text(markup: str) -> str:
    if not markup:
        return ""
    soup = BeautifulSoup(markup, "html.parser")
    for li in soup.find_all("li"):
        li.insert_before("\n• ")
    return _squash(soup.get_text("\n"))


def page_text(soup: BeautifulSoup) -> str:
    """Main readable text of a page, without navigation, scripts and footers."""
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "form", "svg", "iframe"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    for li in main.find_all("li"):
        li.insert_before("\n• ")
    return _squash(main.get_text("\n"))[:MAX_POSTING_CHARS]


def _squash(text: str) -> str:
    """Collapse whitespace, drop blank lines, and join list bullets to their item text."""
    lines: list[str] = []
    pending_bullet = False
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        if line == "•":
            pending_bullet = True
            continue
        lines.append(f"• {line}" if pending_bullet and not line.startswith("•") else line)
        pending_bullet = False
    return "\n".join(lines).strip()


def _posting(title: str, url: str, text: str, location: str = "") -> RawPosting:
    title = " ".join(str(title).split())
    body = _squash(f"{title}\n{('Location: ' + location) if location else ''}\n{text}")
    return RawPosting(title, url, [SourceDocument(Path(title[:80] or "posting"), ContentKind.TEXT,
                                                  text=body[:MAX_POSTING_CHARS])])


def _capped(postings: list[RawPosting], max_postings: int) -> FetchResult:
    result = FetchResult(postings=postings[:max_postings])
    if len(postings) > max_postings:
        result.notes.append(f"Only the first {max_postings} of {len(postings)} roles were considered.")
    return result
