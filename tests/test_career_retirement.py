import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "src" / "tactics_ui"


class CareerRetirementTests(unittest.TestCase):
    def test_career_mode_ui_is_removed_and_experiment_controls_remain(self):
        index = (UI / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("save-mode.js", index)
        self.assertNotIn("save-mode.css", index)
        self.assertIn("workspace-controls.js", index)
        self.assertIn("workspace.css", index)
        self.assertFalse((UI / "save-mode.js").exists())
        self.assertFalse((UI / "save-mode.css").exists())
        self.assertIn("战术执行力实验", (UI / "workspace-controls.js").read_text(encoding="utf-8"))

    def test_career_ui_endpoints_and_storage_keys_are_removed(self):
        for path in (UI / "workspace-controls.js", UI / "tactic-pool.js", UI / "squad-editor.js"):
            text = path.read_text(encoding="utf-8")
            for endpoint in ("/api/save/run", "/api/save/load", "/api/save/opponents", "/api/save/preview"):
                self.assertNotIn(endpoint, text)
            self.assertNotIn("career-", text)

    def test_static_server_serves_workspace_assets_only(self):
        server = (ROOT / "src" / "fm27_tactics_server.py").read_text(encoding="utf-8")
        self.assertNotIn("'/save-mode.js'", server)
        self.assertNotIn("'/save-mode.css'", server)
        self.assertIn("'/workspace-controls.js'", server)
        self.assertIn("'/workspace.css'", server)

    def test_legacy_agent_career_surface_is_removed(self):
        for name in ("cli.py", "client.py", "mcp.py", "schemas.py", "drafts.py"):
            text = (ROOT / "src" / "fm27_agent" / name).read_text(encoding="utf-8")
            self.assertNotIn("career_", text, name)
        agent_server = (ROOT / "src" / "fm27_agent_server.py").read_text(encoding="utf-8")
        self.assertNotIn('"/career/', agent_server)
        tactics_server = (ROOT / "src" / "fm27_tactics_server.py").read_text(encoding="utf-8")
        self.assertNotIn("/api/save/run", tactics_server)
        self.assertNotIn("/api/save/load", tactics_server)
        self.assertIn("/api/save/selection", tactics_server)

    def test_experiment_and_squad_capabilities_are_preserved(self):
        controls = (UI / "workspace-controls.js").read_text(encoding="utf-8")
        self.assertIn("战术执行力实验", controls)
        self.assertIn("experiment-panel", controls)
        self.assertIn("resultsView", controls)
        squad = (UI / "squad-editor.js").read_text(encoding="utf-8")
        self.assertIn("/api/save/selection", squad)
        self.assertIn("showSquadSelection", squad)
        self.assertNotIn("/api/save/load", squad)


if __name__ == "__main__":
    unittest.main()
