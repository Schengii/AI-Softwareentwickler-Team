"""
tests/test_cloud_deployment.py – Testet Cloud-Preview-Deployments & Manifest-Generierung (core/cloud_deployment.py)
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.cloud_deployment import CloudDeploymentManager


class TestCloudDeployment(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        self.mgr = CloudDeploymentManager(self.project_dir)

    def test_detect_stack_python(self):
        (self.project_dir / "requirements.txt").write_text("fastapi\nuvicorn", encoding="utf-8")
        self.assertEqual(self.mgr.detect_stack(), "python")

    def test_detect_stack_node(self):
        (self.project_dir / "package.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.mgr.detect_stack(), "node")

    def test_detect_stack_static(self):
        (self.project_dir / "index.html").write_text("<h1>Hi</h1>", encoding="utf-8")
        self.assertEqual(self.mgr.detect_stack(), "static")

    def test_generate_fly_manifests(self):
        (self.project_dir / "requirements.txt").write_text("fastapi", encoding="utf-8")
        created = self.mgr.generate_manifests(provider="fly")
        self.assertIn("fly.toml", created)
        self.assertIn("Dockerfile", created)

        fly_content = (self.project_dir / "fly.toml").read_text(encoding="utf-8")
        self.assertIn("internal_port = 8000", fly_content)
        self.assertIn("force_https = true", fly_content)

    def test_generate_vercel_manifests(self):
        (self.project_dir / "requirements.txt").write_text("fastapi", encoding="utf-8")
        (self.project_dir / "main.py").write_text("app = None", encoding="utf-8")
        created = self.mgr.generate_manifests(provider="vercel")
        self.assertIn("vercel.json", created)

        vercel_content = (self.project_dir / "vercel.json").read_text(encoding="utf-8")
        self.assertIn("@vercel/python", vercel_content)

    def test_generate_render_manifests(self):
        (self.project_dir / "package.json").write_text("{}", encoding="utf-8")
        created = self.mgr.generate_manifests(provider="render")
        self.assertIn("render.yaml", created)

        render_content = (self.project_dir / "render.yaml").read_text(encoding="utf-8")
        self.assertIn("env: node", render_content)

    def test_dry_run_deployment(self):
        (self.project_dir / "index.html").write_text("<h1>Hello</h1>", encoding="utf-8")
        result = self.mgr.deploy(provider="fly", dry_run=True)
        self.assertTrue(result.attempted)
        self.assertTrue(result.success)
        self.assertTrue(result.preview_url.startswith("https://"))
        self.assertIn(".fly.dev", result.preview_url)

    def test_real_deploy_for_render_is_honestly_reported_as_not_possible(self):
        # Bugfix (realer Fund): ein "echter" Deploy-Versuch für render/railway behauptete
        # bisher UNGEPRÜFT success=True, obwohl nie irgendein Deploy-Befehl ausgeführt wurde -
        # beide Provider deployen über eine Git-Integration im eigenen Dashboard, kein
        # lokales CLI-Kommando.
        (self.project_dir / "package.json").write_text("{}", encoding="utf-8")
        result = self.mgr.deploy(provider="render", dry_run=False)

        self.assertFalse(result.attempted)
        self.assertFalse(result.success)
        self.assertIn("Git-Integration", result.reason_skipped)

    def test_real_deploy_for_railway_is_honestly_reported_as_not_possible(self):
        result = self.mgr.deploy(provider="railway", dry_run=False)
        self.assertFalse(result.attempted)

    def test_dry_run_for_render_still_generates_manifests_and_claims_no_real_deploy(self):
        (self.project_dir / "package.json").write_text("{}", encoding="utf-8")
        result = self.mgr.deploy(provider="render", dry_run=True)

        self.assertTrue(result.attempted)
        self.assertTrue(result.success)
        self.assertIn("render.yaml", result.generated_files)

    @patch("core.cloud_deployment.shutil.which", return_value="/usr/local/bin/vercel")
    @patch("core.cloud_deployment.subprocess.run")
    def test_real_vercel_deploy_actually_invokes_the_cli(self, mock_run, _mock_which):
        # Bugfix (realer Fund): ein "echter" Vercel-Deploy prüfte bisher nur, ob die CLI
        # installiert ist, rief sie aber NIE tatsächlich auf - der generische Fallback
        # behauptete stattdessen einfach success=True mit einer geratenen URL.
        mock_run.return_value = type("R", (), {
            "returncode": 0, "stdout": "https://mein-projekt-abc123.vercel.app\n", "stderr": "",
        })()
        (self.project_dir / "main.py").write_text("app = None", encoding="utf-8")
        (self.project_dir / "requirements.txt").write_text("fastapi", encoding="utf-8")

        result = self.mgr.deploy(provider="vercel", dry_run=False)

        mock_run.assert_called_once()
        called_command = mock_run.call_args[0][0]
        self.assertEqual(called_command[0], "vercel")
        self.assertTrue(result.success)
        self.assertEqual(result.preview_url, "https://mein-projekt-abc123.vercel.app")


if __name__ == "__main__":
    unittest.main()
