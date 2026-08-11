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
