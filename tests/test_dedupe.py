"""Tests for dedupe's repository normalisation and keeper selection."""

from commands.dedupe import _norm_repo, _pick_keeper


def test_norm_repo_canonicalises():
    assert _norm_repo({"repository": "https://github.com/A/B.git/"}) == "https://github.com/a/b"
    assert _norm_repo({"repository": "HTTPS://GitHub.com/A/B"}) == "https://github.com/a/b"
    assert _norm_repo({}) == ""


def test_keeper_prefers_upstream():
    a = {"id": "alias", "repository": "r", "packages": [1]}
    b = {"id": "canonical", "repository": "r"}
    assert _pick_keeper([a, b], upstream={"canonical"}) is b


def test_keeper_prefers_richer_then_shorter_id_when_neither_upstream():
    short = {"id": "overt", "repository": "r", "downloads": 1}
    long = {"id": "overt-app", "repository": "r", "downloads": 1}
    # equal richness -> shorter id wins
    assert _pick_keeper([long, short], upstream=set()) is short


def test_keeper_prefers_more_keys():
    thin = {"id": "aa", "repository": "r"}
    rich = {"id": "bb", "repository": "r", "electron": "20.0.0", "downloads": 1}
    assert _pick_keeper([thin, rich], upstream=set()) is rich
