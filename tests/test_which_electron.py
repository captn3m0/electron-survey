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


class _FakeDownloads:
    """Stub _download/_run_which_electron so process() can be driven offline.

    ``results`` maps a URL to what which-electron would report, or None to
    simulate a download that never landed.
    """

    def __init__(self, monkeypatch, results):
        self.results = results
        self.inspected = []
        monkeypatch.setattr(we, "_download", self._download)
        monkeypatch.setattr(we, "_run_which_electron", self._run)

    def _download(self, url):
        import pathlib
        if self.results[url] is None:
            return None
        self._current = url
        # Never created on disk; process() unlinks it with missing_ok=True.
        return pathlib.Path("/nonexistent/fake-artefact")

    def _run(self, path):
        self.inspected.append(self._current)
        return self.results[self._current]


def test_process_returns_the_first_version_found(monkeypatch):
    entry = {"id": "x", "packages": [{"url": "https://x/App.deb"}, {"url": "https://x/App.dmg"}]}
    _FakeDownloads(monkeypatch, {
        "https://x/App.deb": {"version": "v35.6.0", "method": "rg"},
        "https://x/App.dmg": {"signals": []},
    })
    assert we.process(entry) == {
        "electron": "35.6.0",
        "method": "which-electron-rg",
        "evidence": {
            "kind": "binary",
            "source": "https://x/App.deb",
            "found_in": "App.deb",
            "signal": "which-electron rg signal",
        },
    }


def test_process_records_which_artefact_answered(monkeypatch):
    """The first candidate is unreadable, so the evidence must name the second."""
    entry = {"id": "x", "packages": [{"url": "https://x/App.deb"}, {"url": "https://x/App.dmg"}]}
    _FakeDownloads(monkeypatch, {
        "https://x/App.deb": {"signals": []},
        "https://x/App.dmg": {"version": "v20.0.0", "method": "fingerprint"},
    })
    evidence = we.process(entry)["evidence"]
    assert evidence["found_in"] == "App.dmg"
    assert evidence["source"] == "https://x/App.dmg"


def test_process_marks_checked_only_when_every_artefact_was_read(monkeypatch):
    entry = {"id": "x", "packages": [{"url": "https://x/App.deb"}, {"url": "https://x/App.dmg"}]}
    _FakeDownloads(monkeypatch, {
        "https://x/App.deb": {"signals": []},
        "https://x/App.dmg": {"signals": []},
    })
    assert we.process(entry) == {"we_tried": we._signature(entry)}


def test_process_leaves_app_queued_when_an_artefact_failed_to_download(monkeypatch):
    """A partial failure must not retire the app: the artefact that failed is
    often the only readable one (typora's .deb was)."""
    entry = {"id": "x", "packages": [{"url": "https://x/App.deb"}, {"url": "https://x/App.dmg"}]}
    _FakeDownloads(monkeypatch, {
        "https://x/App.deb": None,          # transient failure
        "https://x/App.dmg": {"signals": []},  # readable, but tells us nothing
    })
    assert we.process(entry) is None
    assert we.matches(entry) is True


def test_process_returns_none_when_nothing_downloaded(monkeypatch):
    entry = {"id": "x", "packages": [{"url": "https://x/App.deb"}]}
    _FakeDownloads(monkeypatch, {"https://x/App.deb": None})
    assert we.process(entry) is None


def test_session_sends_a_non_default_user_agent():
    """Vendor CDNs (exodus.com) 403 the default python-requests UA."""
    ua = we._SESSION.headers["User-Agent"]
    assert "python-requests" not in ua
    assert "electron-survey" in ua


def test_process_treats_a_tool_crash_as_unread_not_as_a_clean_miss(monkeypatch):
    """which-electron returning no JSON means it failed to look, which is not
    the same as looking and finding nothing (an empty signals list)."""
    entry = {"id": "x", "packages": [{"url": "https://x/App.AppImage"}]}
    _FakeDownloads(monkeypatch, {"https://x/App.AppImage": None})

    import pathlib
    monkeypatch.setattr(we, "_download", lambda url: pathlib.Path("/nonexistent/a"))
    monkeypatch.setattr(we, "_run_which_electron", lambda path: None)  # crashed

    assert we.process(entry) is None
    assert we.matches(entry) is True


def test_resolved_apps_are_not_reclaimed_by_default():
    entry = {"id": "x", "electron": "30.0.0", "method": "which-electron-rg",
             "packages": [{"url": "https://x/App.deb"}]}
    assert we.matches(entry) is False


def test_backfill_flag_reclaims_only_binary_results_missing_evidence(monkeypatch):
    monkeypatch.setattr(we, "_BACKFILL_EVIDENCE", True)
    binary_no_evidence = {"id": "x", "electron": "30.0.0", "method": "which-electron-rg",
                          "packages": [{"url": "https://x/App.deb"}]}
    binary_with_evidence = {**binary_no_evidence, "evidence": {"kind": "binary"}}
    lockfile_result = {"id": "y", "electron": "30.0.0", "method": "src-package-lock",
                       "packages": [{"url": "https://y/App.deb"}]}

    assert we.matches(binary_no_evidence) is True
    assert we.matches(binary_with_evidence) is False
    # A lockfile reading is not this processor's to re-derive.
    assert we.matches(lockfile_result) is False
