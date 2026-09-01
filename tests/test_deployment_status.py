"""
tests/test_deployment_status.py – Testet core/deployment_status.py (persistenter
Live-Deployment-Zustand pro Projekt)
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import core.deployment_status as deployment_status


class TestDeploymentStatus(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_read_deployment_is_none_without_a_prior_deploy(self):
        self.assertIsNone(deployment_status.read_deployment(self.temp_dir))

    def test_record_and_read_deployment_round_trip(self):
        deployment_status.record_deployment(self.temp_dir, provider="fly", url="https://x.fly.dev")
        data = deployment_status.read_deployment(self.temp_dir)

        self.assertEqual(data["provider"], "fly")
        self.assertEqual(data["url"], "https://x.fly.dev")
        self.assertIsNone(data["last_check_healthy"])

    def test_record_health_check_updates_existing_deployment(self):
        deployment_status.record_deployment(self.temp_dir, provider="fly", url="https://x.fly.dev")
        deployment_status.record_health_check(self.temp_dir, healthy=False, detail="HTTP 503")
        data = deployment_status.read_deployment(self.temp_dir)

        self.assertFalse(data["last_check_healthy"])
        self.assertEqual(data["last_check_detail"], "HTTP 503")
        self.assertEqual(data["url"], "https://x.fly.dev")  # unverändert

    def test_health_check_without_prior_deployment_is_a_safe_noop(self):
        deployment_status.record_health_check(self.temp_dir, healthy=True, detail="OK")
        self.assertIsNone(deployment_status.read_deployment(self.temp_dir))

    def test_corrupted_file_is_treated_as_no_deployment(self):
        (Path(self.temp_dir) / deployment_status.DEPLOYMENT_STATUS_FILENAME).write_text("{bad json", encoding="utf-8")
        self.assertIsNone(deployment_status.read_deployment(self.temp_dir))

    def test_list_all_deployments_finds_every_deployed_project(self):
        base = Path(self.temp_dir)
        (base / "proj_a").mkdir()
        (base / "proj_b").mkdir()
        (base / "proj_c").mkdir()  # nie deployt
        deployment_status.record_deployment(base / "proj_a", provider="fly", url="https://a.fly.dev")
        deployment_status.record_deployment(base / "proj_b", provider="vercel", url="https://b.vercel.app")

        results = deployment_status.list_all_deployments(base)

        self.assertEqual([slug for slug, _ in results], ["proj_a", "proj_b"])

    def test_list_all_deployments_on_missing_workspace_returns_empty(self):
        self.assertEqual(deployment_status.list_all_deployments(Path(self.temp_dir) / "does-not-exist"), [])


if __name__ == "__main__":
    unittest.main()
