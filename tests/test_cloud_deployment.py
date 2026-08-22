"""
tests/test_cloud_deployment.py – Testet Cloud-Preview-Deployments & Manifest-Generierung (core/cloud_deployment.py)
"""

import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
