import pytest


@pytest.fixture(autouse=True)
def isolated_extract_cache(tmp_path, monkeypatch):
    """Tests use fake model answers; they must never land in the real extraction cache (runs/.extract_cache)."""
    from legacy_portal import extract
    monkeypatch.setattr(extract, "CACHE_DIR", tmp_path / "extract_cache")
