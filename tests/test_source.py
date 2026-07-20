"""Tests for the source-archive Electron detection parsers."""

import semantic_version

from tests.steploader import load_step

source = load_step("source.py")


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


# --- package-lock.json -----------------------------------------------------

def test_package_lock_v3_packages(tmp_path):
    p = _write(tmp_path, "package-lock.json",
               '{"packages": {"node_modules/electron": {"version": "22.3.1"}}}')
    assert source._electron_from_package_lock([p]) == "22.3.1"


def test_package_lock_v1_dependencies(tmp_path):
    p = _write(tmp_path, "package-lock.json",
               '{"dependencies": {"electron": {"version": "18.0.4"}}}')
    assert source._electron_from_package_lock([p]) == "18.0.4"


def test_package_lock_no_electron(tmp_path):
    p = _write(tmp_path, "package-lock.json",
               '{"packages": {"node_modules/react": {"version": "18.2.0"}}}')
    assert source._electron_from_package_lock([p]) is None


def test_package_lock_malformed_is_skipped(tmp_path):
    bad = _write(tmp_path, "a.json", "{not json")
    good = _write(tmp_path, "b.json",
                  '{"dependencies": {"electron": {"version": "9.4.4"}}}')
    assert source._electron_from_package_lock([bad, good]) == "9.4.4"


# --- yarn.lock -------------------------------------------------------------

def test_yarn_classic(tmp_path):
    p = _write(tmp_path, "yarn.lock",
               'electron@^20.0.0:\n  version "20.1.0"\n  resolved "x"\n')
    assert source._electron_from_yarn_lock([p]) == "20.1.0"


def test_yarn_berry(tmp_path):
    p = _write(tmp_path, "yarn.lock",
               '"electron@npm:^24.0.0":\n  version: 24.1.2\n  resolution: "electron@npm:24.1.2"\n')
    assert source._electron_from_yarn_lock([p]) == "24.1.2"


def test_yarn_ignores_electron_prefixed_packages(tmp_path):
    # electron-store should not be mistaken for electron
    p = _write(tmp_path, "yarn.lock",
               'electron-store@^8:\n  version "8.1.0"\n')
    assert source._electron_from_yarn_lock([p]) is None


# --- pnpm-lock.yaml --------------------------------------------------------

def test_pnpm_v8_slash_key(tmp_path):
    p = _write(tmp_path, "pnpm-lock.yaml",
               "packages:\n  /electron/20.1.0:\n    resolution: {integrity: sha}\n")
    assert source._electron_from_pnpm_lock([p]) == "20.1.0"


def test_pnpm_v8_at_key(tmp_path):
    p = _write(tmp_path, "pnpm-lock.yaml",
               "packages:\n  /electron@27.0.2:\n    resolution: {integrity: sha}\n")
    assert source._electron_from_pnpm_lock([p]) == "27.0.2"


def test_pnpm_v9_snapshots(tmp_path):
    p = _write(tmp_path, "pnpm-lock.yaml",
               "snapshots:\n  electron@31.0.0: {}\n")
    assert source._electron_from_pnpm_lock([p]) == "31.0.0"


# --- package.json range ----------------------------------------------------

def test_package_json_devdep_range(tmp_path):
    p = _write(tmp_path, "package.json",
               '{"devDependencies": {"electron": "^20.0.0"}}')
    assert source._electron_range_from_package_json([p]) == "^20.0.0"


def test_package_json_prefers_devdep_over_dep(tmp_path):
    p = _write(tmp_path, "package.json",
               '{"dependencies": {"electron": "1.0.0"}, "devDependencies": {"electron": "25.0.0"}}')
    assert source._electron_range_from_package_json([p]) == "25.0.0"


# --- range resolution ------------------------------------------------------

def test_resolve_range_picks_highest_matching(monkeypatch):
    monkeypatch.setattr(source, "_known_versions",
                        [semantic_version.Version(v) for v in ("19.0.0", "20.1.0", "20.3.0", "21.0.0")])
    assert source._resolve_range("^20.0.0") == "20.3.0"


def test_resolve_range_no_match(monkeypatch):
    monkeypatch.setattr(source, "_known_versions",
                        [semantic_version.Version("19.0.0")])
    assert source._resolve_range("^25.0.0") is None


def test_resolve_range_invalid_spec(monkeypatch):
    monkeypatch.setattr(source, "_known_versions", [semantic_version.Version("20.0.0")])
    assert source._resolve_range("not-a-range") is None


# --- helpers ---------------------------------------------------------------

def test_by_depth_orders_shallowest_first(tmp_path):
    import pathlib
    paths = [pathlib.Path("a/b/c/package.json"), pathlib.Path("package.json"), pathlib.Path("a/package.json")]
    ordered = source._by_depth(paths)
    assert ordered[0] == pathlib.Path("package.json")
    assert ordered[-1] == pathlib.Path("a/b/c/package.json")


# --- matches / refresh semantics -------------------------------------------

def test_matches_requires_src():
    assert source.matches({"id": "x"}) is False
    assert source.matches({"id": "x", "src": "u"}) is True


def test_matches_skips_current_src_detection():
    e = {"id": "x", "src": "u1", "electron": "20.0.0",
         "method": "src-package-lock", "electron_src": "u1"}
    assert source.matches(e) is False


def test_matches_redetects_when_src_advanced():
    # new release: github.com moved src to u2, but electron_src still points at u1
    e = {"id": "x", "src": "u2", "electron": "20.0.0",
         "method": "src-package-lock", "electron_src": "u1"}
    assert source.matches(e) is True


def test_matches_does_not_override_other_methods():
    e = {"id": "x", "src": "u1", "electron": "43.1.1", "method": "which-electron-rg"}
    assert source.matches(e) is False
    e2 = {"id": "x", "src": "u1", "electron": "39.8.3", "method": "aur-depends"}
    assert source.matches(e2) is False
