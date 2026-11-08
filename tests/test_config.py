from nova.config import get_settings


def test_defaults_load():
    s = get_settings()
    assert s.base_url.startswith("http")
    assert s.api_key
    assert s.model
    assert s.max_steps > 0
    assert 0.0 <= s.temperature <= 2.0


def test_workspace_and_db_are_paths():
    s = get_settings()
    assert s.workspace.name == "workspace"
    assert s.db.suffix == ".sqlite3"