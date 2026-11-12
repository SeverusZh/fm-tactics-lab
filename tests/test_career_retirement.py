from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "src" / "tactics_ui"


def test_career_mode_ui_is_removed_and_experiment_controls_remain():
    index = (UI / "index.html").read_text(encoding="utf-8")
    assert "save-mode.js" not in index
    assert "save-mode.css" not in index
    assert "workspace-controls.js" in index
    assert "workspace.css" in index
    assert not (UI / "save-mode.js").exists()
    assert not (UI / "save-mode.css").exists()
    assert "战术执行力实验" in (UI / "workspace-controls.js").read_text(encoding="utf-8")


def test_career_ui_endpoints_and_storage_keys_are_removed():
    files = [
        UI / "workspace-controls.js",
        UI / "tactic-pool.js",
        UI / "squad-editor.js",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "/api/save/run" not in text
        assert "/api/save/load" not in text
        assert "/api/save/opponents" not in text
        assert "/api/save/preview" not in text
        assert "fm27-career-" not in text
        assert "career-" not in text


def test_static_server_serves_workspace_assets_only():
    server = (ROOT / "src" / "fm27_tactics_server.py").read_text(encoding="utf-8")
    assert "'/save-mode.js'" not in server
    assert "'/save-mode.css'" not in server
    assert "'/workspace-controls.js'" in server
    assert "'/workspace.css'" in server

def test_legacy_agent_career_surface_is_removed():
    for name in ("cli.py", "client.py", "mcp.py", "schemas.py", "drafts.py"):
        text = (ROOT / "src" / "fm27_agent" / name).read_text(encoding="utf-8")
        assert "career_" not in text, name
    agent_server = (ROOT / "src" / "fm27_agent_server.py").read_text(encoding="utf-8")
    assert '"/career/' not in agent_server
    tactics_server = (ROOT / "src" / "fm27_tactics_server.py").read_text(encoding="utf-8")
    assert "/api/save/run" not in tactics_server
    assert "/api/save/load" not in tactics_server
    assert "/api/save/selection" in tactics_server

def test_experiment_and_squad_capabilities_are_preserved():
    controls = (UI / "workspace-controls.js").read_text(encoding="utf-8")
    assert "战术执行力实验" in controls
    assert "experiment-panel" in controls
    assert "resultsView" in controls
    squad = (UI / "squad-editor.js").read_text(encoding="utf-8")
    assert "/api/save/selection" in squad
    assert "showSquadSelection" in squad
    assert "/api/save/load" not in squad
