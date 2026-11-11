import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from agent_mock import make_pool_scenario, start_server
from fm27_agent.client import AgentError, Client
from fm27_agent.drafts import DraftService


class DraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = start_server()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def setUp(self):
        self.data_dir = tempfile.mkdtemp()
        self.client = Client(base_url=self.server.url, token=self.server.token,
                             data_dir=self.data_dir)
        self.drafts = DraftService(self.client)

    def test_create_edit_validate_delete(self):
        draft = self.drafts.create("default", name="对照")
        self.assertTrue(draft["draft_id"].startswith("dr_"))
        self.assertEqual(len(draft["teams"]), 2)
        edited = self.drafts.edit(draft["draft_id"], "mentality", side=0, value=5)
        self.assertEqual(edited["summary"]["teams"][0]["mentality"], 5)
        edited = self.drafts.edit(draft["draft_id"], "team_instruction", side=0,
                                  phase="in_possession", group=1, option=2)
        self.assertTrue(edited["validation"]["valid"])
        checked = self.drafts.validate(draft["draft_id"])
        self.assertTrue(checked["valid"])
        self.assertEqual(checked["records"], 30)
        self.assertIn(draft["draft_id"], [item["draft_id"] for item in self.drafts.list()])
        self.assertFalse(self.drafts.get(draft["draft_id"], include_scenario=True)["scenario"] is None)
        self.drafts.delete(draft["draft_id"])
        with self.assertRaises(AgentError) as caught:
            self.drafts.get(draft["draft_id"])
        self.assertEqual(caught.exception.code, "not_found")

    def test_invalid_edit_keeps_draft(self):
        draft = self.drafts.create("default")
        path = Path(self.data_dir) / "agent" / "drafts" / (draft["draft_id"] + ".json")
        before = path.read_bytes()
        with self.assertRaises(AgentError) as caught:
            self.drafts.edit(draft["draft_id"], "mentality", side=0, value=99)
        self.assertEqual(caught.exception.code, "validation_failed")
        self.assertEqual(path.read_bytes(), before)

    def test_lineup_and_formation(self):
        draft = self.drafts.create("default")
        edited = self.drafts.edit(draft["draft_id"], "lineup", side=0,
                                  starters=list(range(11)), bench=[11, 12])
        self.assertEqual(edited["summary"]["teams"][0]["roster_size"], 13)
        scenario = self.drafts.scenario(draft["draft_id"])
        self.assertEqual(scenario["teams"][0]["roster_size"], 13)
        edited = self.drafts.edit(draft["draft_id"], "formation", side=1,
                                  phase="in_possession",
                                  positions=["GK", "LB", "CB", "RB", "DM", "CM",
                                             "LM", "RM", "LW", "ST", "RW"])
        self.assertTrue(edited["validation"]["valid"])

    def test_pool_survives_all_creation_sources(self):
        scenario = make_pool_scenario()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pool.json"
            path.write_text(json.dumps(scenario, ensure_ascii=False), encoding="utf-8")
            inline = self.drafts.create("inline", scenario_path=str(path))
        self.assertEqual(inline["away_tactic_pool"], {
            "enabled": True, "entries": 2, "mode": "random", "rounds": 1,
            "players": "uniform", "roster_entries": 0,
            "uniform": {"enabled": True, "attribute_value": 15}})
        cloned = self.drafts.create("draft", base_draft_id=inline["draft_id"])
        self.assertEqual(cloned["away_tactic_pool"]["entries"], 2)
        job = self.client.run(scenario, seeds=[1, 2])
        from_job = self.drafts.create("job", job_id=job["id"], variant="B")
        self.assertEqual(from_job["away_tactic_pool"]["entries"], 2)
        imported = self.drafts.create("fmf", side=1, file_base64="QUFB",
                                      base_draft_id=cloned["draft_id"])
        self.assertEqual(imported["away_tactic_pool"]["entries"], 2)
        stored = self.drafts.scenario(inline["draft_id"])
        self.assertEqual(len(stored["away_tactic_pool"]["entries"]), 2)

    def test_create_from_save_fmf_job_inline(self):
        saved = self.drafts.create("save", save_id="a" * 16, club_uid=1, tactic_index=0)
        self.assertEqual(saved["source"]["kind"], "save")
        fmf = self.drafts.create("fmf", side=0, file_base64="QUFB",
                                 base_draft_id=saved["draft_id"])
        self.assertEqual(fmf["source"]["kind"], "fmf")
        job = self.client.run(self.client.defaults()["scenario"], seeds=[1])
        from_job = self.drafts.create("job", job_id=job["id"], variant="B")
        self.assertEqual(from_job["source"]["kind"], "job")
        inline = self.drafts.create("inline", scenario=self.client.defaults()["scenario"])
        self.assertEqual(inline["source"]["kind"], "inline")


if __name__ == "__main__":
    unittest.main()
