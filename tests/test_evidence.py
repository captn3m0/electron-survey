"""Tests for rebuilding provenance for apps resolved before it was recorded."""

from commands.evidence import _aur_evidence, _src_evidence

INDEX = {"chia-bin": ["electron39", "nodejs"], "unrelated": ["gtk3"]}


def test_aur_evidence_names_the_package_and_depend():
    entry = {"id": "chia", "electron": "39.8.5", "aur": ["unrelated", "chia-bin"]}
    ev = _aur_evidence(entry, INDEX)
    assert ev["found_in"] == "chia-bin"
    assert ev["source"] == "https://aur.archlinux.org/packages/chia-bin"
    assert "electron39" in ev["signal"]


def test_aur_evidence_is_skipped_when_the_aur_no_longer_agrees():
    """The package has moved to a new Electron since the version was recorded;
    claiming it as the source would be fabricating provenance."""
    entry = {"id": "chia", "electron": "30.0.0", "aur": ["chia-bin"]}
    assert _aur_evidence(entry, INDEX) is None


def test_aur_evidence_is_none_without_a_matching_package():
    entry = {"id": "x", "electron": "39.8.5", "aur": ["unrelated"]}
    assert _aur_evidence(entry, INDEX) is None


def test_src_evidence_uses_the_archive_the_version_came_from():
    """electron_src is the archive that was actually read; src may have moved on."""
    entry = {
        "id": "x", "electron": "30.1.2", "method": "src-package-lock",
        "electron_src": "https://example.test/v1.zip",
        "src": "https://example.test/v2.zip",
    }
    ev = _src_evidence(entry)
    assert ev["source"] == "https://example.test/v1.zip"
    assert ev["found_in"] == "package-lock.json"
    assert ev["kind"] == "lockfile"
    assert ev["reconstructed"] is True


def test_src_evidence_falls_back_to_src_when_no_archive_recorded():
    entry = {"id": "x", "electron": "1.0.0", "method": "src-yarn-lock",
             "src": "https://example.test/only.zip"}
    assert _src_evidence(entry)["source"] == "https://example.test/only.zip"


def test_range_guess_is_flagged_as_a_manifest_not_a_lockfile():
    entry = {"id": "x", "electron": "30.9.9", "method": "src-range-guess",
             "electron_src": "https://example.test/v1.zip"}
    ev = _src_evidence(entry)
    assert ev["kind"] == "manifest"
    assert "range" in ev["signal"]


def test_src_evidence_is_none_without_an_archive():
    assert _src_evidence({"id": "x", "electron": "1.0.0", "method": "src-yarn-lock"}) is None


def test_unknown_method_yields_no_evidence():
    entry = {"id": "x", "electron": "1.0.0", "method": "which-electron-rg",
             "electron_src": "https://example.test/v1.zip"}
    assert _src_evidence(entry) is None
