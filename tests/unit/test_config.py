def test_settings_use_nidaro_prefix(monkeypatch):
    from nidaro.config import Settings

    monkeypatch.setenv("NIDARO_TIMEZONE", "UTC")
    assert Settings().timezone == "UTC"


def test_uuid_is_unique():
    from nidaro.db.types import new_uuid

    assert new_uuid() != new_uuid()
