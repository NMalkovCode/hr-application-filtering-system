from __future__ import annotations

from pathlib import Path

from hr_screening import filter_cache
from hr_screening.filters import FilterSet, FilterType, ScreeningFilter
from hr_screening.models import ContentKind, SourceDocument


def _docs(text: str) -> list[SourceDocument]:
    return [SourceDocument(Path("jd.txt"), ContentKind.TEXT, text=text)]


def _set(title="Data Analyst") -> FilterSet:
    return FilterSet(job_title=title, filters=[
        ScreeningFilter(id="F01", criterion="SQL", type=FilterType.MUST_HAVE, weight=5),
    ])


def test_save_and_find_ignores_whitespace_and_case(tmp_path: Path):
    filter_cache.save_filter_set(_docs("Senior Data Analyst\nSQL required"), _set(), base=tmp_path)
    found = filter_cache.find_filter_set(_docs("  senior data   analyst SQL REQUIRED "), base=tmp_path)
    assert found is not None
    assert found.filter_set == _set()
    assert found.excerpt.startswith("Senior Data Analyst")
    assert filter_cache.find_filter_set(_docs("Different role"), base=tmp_path) is None


def test_resaving_overwrites(tmp_path: Path):
    docs = _docs("JD")
    filter_cache.save_filter_set(docs, _set("Old"), base=tmp_path)
    filter_cache.save_filter_set(docs, _set("New"), base=tmp_path)
    (entry,) = filter_cache.list_filter_sets(base=tmp_path)
    assert entry.filter_set.job_title == "New"


def test_corrupt_entries_are_skipped(tmp_path: Path):
    filter_cache.save_filter_set(_docs("JD"), _set(), base=tmp_path)
    (tmp_path / "filters" / "broken.json").write_text("{", encoding="utf-8")
    assert len(filter_cache.list_filter_sets(base=tmp_path)) == 1


def test_delete_and_clear(tmp_path: Path):
    a = filter_cache.save_filter_set(_docs("A"), _set("A"), base=tmp_path)
    filter_cache.save_filter_set(_docs("B"), _set("B"), base=tmp_path)
    (tmp_path / "roles").mkdir()
    (tmp_path / "roles" / "x.json").write_text("{}", encoding="utf-8")

    filter_cache.delete_filter_set(a.fingerprint, base=tmp_path)
    assert [e.filter_set.job_title for e in filter_cache.list_filter_sets(base=tmp_path)] == ["B"]

    assert filter_cache.clear_cache(base=tmp_path) == 2
    assert list(tmp_path.iterdir()) == []
