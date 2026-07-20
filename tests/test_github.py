"""Tests for the github.com processor's pure helpers."""

from tests.steploader import load_step

gh = load_step("github.com.py")


def test_parse_owner_repo():
    assert gh._parse_owner_repo("https://github.com/electron/fiddle") == ("electron", "fiddle")
    assert gh._parse_owner_repo("https://github.com/owner/repo.git") == ("owner", "repo")
    assert gh._parse_owner_repo("https://www.github.com/a/b/") == ("a", "b")


def test_parse_owner_repo_rejects_non_github():
    assert gh._parse_owner_repo("https://gitlab.com/a/b") is None
    assert gh._parse_owner_repo("https://github.com/only-owner") is None


def test_parse_checksums_plain_and_star():
    text = "abc123  app-linux.deb\ndef456  *app-mac.dmg\n# a comment\n\n"
    parsed = gh._parse_checksums(text)
    assert parsed == {"app-linux.deb": "abc123", "app-mac.dmg": "def456"}


def test_parse_checksums_ignores_odd_lines():
    text = "onlyonefield\nhash file extra\n"
    assert gh._parse_checksums(text) == {}
