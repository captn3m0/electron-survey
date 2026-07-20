"""Tests for which-electron candidate selection and the we_tried marker."""

from tests.steploader import load_step

we = load_step("which-electron.py")


def test_ext_of_handles_multipart_and_query():
    assert we._ext_of("https://x/app.tar.gz?token=1") == ".tar.gz"
    assert we._ext_of("https://x/App.DMG") == ".dmg"
    assert we._ext_of("https://x/App.AppImage") == ".appimage"


def test_candidate_urls_filters_and_orders():
    entry = {
        "downloads": [
            {"url": "https://x/App-setup.exe"},       # skipped (installer)
            {"url": "https://x/App.dmg.blockmap"},     # skipped (blockmap)
            {"url": "https://x/App.dmg"},              # kept, priority 4
            {"url": "https://x/App.deb"},              # kept, priority 0
            {"url": "https://x/latest-mac.yml"},       # skipped (yml)
            {"url": "https://x/notes.txt"},            # skipped (bad ext)
        ]
    }
    urls = we._candidate_urls(entry)
    assert urls == ["https://x/App.deb", "https://x/App.dmg"]


def test_candidate_urls_dedupes():
    entry = {
        "downloads": [{"url": "https://x/App.AppImage"}],
        "packages": [{"url": "https://x/App.AppImage"}],
    }
    assert we._candidate_urls(entry) == ["https://x/App.AppImage"]


def test_signature_includes_epoch_and_latest():
    sig = we._signature({"id": "x", "latest": "v5.0.0"})
    assert sig == f"{we._EPOCH}:v5.0.0"


def test_signature_falls_back_to_url_hash():
    sig = we._signature({"id": "x", "downloads": [{"url": "https://x/App.deb"}]})
    assert sig.startswith(f"{we._EPOCH}:urls:")


def test_matches_skips_resolved_and_already_tried():
    base = {"id": "x", "latest": "v5.0.0", "downloads": [{"url": "https://x/App.deb"}]}
    assert we.matches(base) is True
    assert we.matches({**base, "electron": "5.0.0"}) is False
    assert we.matches({**base, "dead": True}) is False
    assert we.matches({**base, "we_tried": we._signature(base)}) is False
    # a new release changes the signature, so the app is re-opened
    assert we.matches({**base, "we_tried": f"{we._EPOCH}:v4.0.0"}) is True


def test_matches_needs_a_candidate():
    assert we.matches({"id": "x", "downloads": [{"url": "https://x/readme.txt"}]}) is False


def test_matches_overrides_low_confidence_methods():
    base = {"id": "x", "latest": "v5.0.0", "electron": "39.8.3",
            "downloads": [{"url": "https://x/App.deb"}]}
    # approximate methods are re-checked (binary fingerprint is authoritative)
    assert we.matches({**base, "method": "aur-depends"}) is True
    assert we.matches({**base, "method": "src-range-guess"}) is True
    # exact / already-authoritative methods are left alone
    assert we.matches({**base, "method": "src-package-lock"}) is False
    assert we.matches({**base, "method": "which-electron-rg"}) is False
    # but not re-checked once tried at this release
    assert we.matches({**base, "method": "aur-depends",
                       "we_tried": we._signature(base)}) is False
