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
