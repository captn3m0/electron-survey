"""Tests for the AUR processor: URL helpers, indexing, matching, repo recovery."""

import pytest

from tests.steploader import load_step

aur = load_step("aur.py")

_FAKE_META = """[
 {"Name":"foo-bin","URL":"https://foo.example.com/download","Depends":[]},
 {"Name":"bar","URL":"https://github.com/barorg/bar","Depends":[]},
 {"Name":"slack-desktop","URL":"https://slack.com/","Depends":[]}
]"""


@pytest.fixture
def fake_meta(tmp_path, monkeypatch):
    meta = tmp_path / "meta.json"
    meta.write_text(_FAKE_META)
    monkeypatch.setattr(aur, "META_FILE", str(meta))
    aur._load_index.cache_clear()
    yield
    aur._load_index.cache_clear()


def test_github_repo_extraction():
    assert aur._github_repo("https://github.com/barorg/bar") == "https://github.com/barorg/bar"
    assert aur._github_repo("https://github.com/barorg/bar.git/") == "https://github.com/barorg/bar"
    assert aur._github_repo("https://foo.example.com/") is None
    assert aur._github_repo("https://github.com/only-owner") is None


def test_host_strips_www():
    assert aur._host("https://www.Example.com/path") == "example.com"


def test_match_by_website_domain(fake_meta):
    result = aur.process({"id": "whatever", "website": "https://foo.example.com"})
    assert result["aur"] == ["foo-bin"]
    # non-github upstream URL: no repository recovered
    assert "repository" not in result


def test_match_by_id_recovers_github_repo(fake_meta):
    result = aur.process({"id": "bar"})
    assert result["aur"] == ["bar"]
    assert result["repository"] == "https://github.com/barorg/bar"


def test_generic_domain_falls_through_to_id(fake_meta):
    # github.com is a generic host, so it must not match by domain; id has no
    # package here, so nothing is found.
    assert aur.process({"id": "nomatch", "website": "https://github.com/x/y"}) is None


def test_existing_repository_not_overwritten(fake_meta):
    result = aur.process({"id": "bar", "repository": "https://github.com/keep/this"})
    assert "repository" not in result  # keeper untouched; only aur returned


def test_matches_respects_opt_out():
    assert aur.matches({"id": "x", "aur": False}) is False
    assert aur.matches({"id": "x", "aur": ["already"]}) is False
    assert aur.matches({"id": "x", "website": "https://a.com"}) is True
