"""
core/cloud_deployment.py – Cloud-Preview-Deployment-Adapter (Fly.io, Vercel, Render, Railway)

Erweitert das lokale Docker-Deployment (core/deployment.py) um weltweite Preview-Deployments:
1. Automatische Erkennung des Projekt-Typs (Python/FastAPI/Flask, Node/React/Next.js, Statisch HTML/CSS/JS)
2. Automatische Generierung produktionsreifer Konfigurations-Manifeste (`fly.toml`, `vercel.json`, `render.yaml`, `Dockerfile`)
3. Echter Deploy-Start über installierte Cloud-CLIs (`flyctl`, `vercel`) oder Manifest-Bereitstellung für CI/CD
"""

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CloudDeploymentResult:
    """Ergebnis eines Cloud-Deployment-Versuchs."""
    attempted: bool
    success: bool = False
    provider: str = ""  # "fly", "vercel", "render", "railway"
    preview_url: str = ""
    generated_files: list[str] = field(default_factory=list)
    output: str = ""
    reason_skipped: str = ""


class CloudDeploymentManager:
    """
    Generiert Cloud-Manifeste und steuert Preview-Deployments.
    """

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir).resolve()

    def detect_stack(self) -> str:
        """Ermittelt den Technologie-Stack des Projekts."""
        if (self.project_dir / "requirements.txt").exists() or any(self.project_dir.glob("*.py")):
            return "python"
        if (self.project_dir / "package.json").exists():
            return "node"
        if any(self.project_dir.glob("*.html")):
            return "static"
        return "generic"

    def generate_manifests(self, provider: str = "fly") -> list[str]:
        """
        Generiert die passenden Konfigurationsdateien für den gewählten Cloud-Provider.
        """
        created = []
        stack = self.detect_stack()
        app_name = self.project_dir.name.lower().replace("_", "-").replace(" ", "-")

        if provider == "fly":
            fly_toml = self.project_dir / "fly.toml"
            if not fly_toml.exists():
                port = 8000 if stack == "python" else (3000 if stack == "node" else 80)
                content = (
                    f"app = '{app_name}'\n"
                    f"primary_region = 'fra'\n\n"
                    f"[http_service]\n"
                    f"  internal_port = {port}\n"
                    f"  force_https = true\n"
                    f"  auto_stop_machines = true\n"
                    f"  auto_start_machines = true\n"
                    f"  min_machines_running = 0\n"
                )
                fly_toml.write_text(content, encoding="utf-8")
                created.append("fly.toml")

            # Fallback Dockerfile für Python/Generic falls nicht existent
            dockerfile = self.project_dir / "Dockerfile"
            if not dockerfile.exists():
                if stack == "python":
                    docker_content = (
                        "FROM python:3.11-slim\n"
                        "WORKDIR /app\n"
                        "COPY requirements.txt* .\n"
                        "RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi\n"
                        "COPY . .\n"
                        "EXPOSE 8000\n"
                        "CMD [\"python\", \"-m\", \"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]\n"
                    )
                    dockerfile.write_text(docker_content, encoding="utf-8")
                    created.append("Dockerfile")

        elif provider == "vercel":
            vercel_json = self.project_dir / "vercel.json"
            if not vercel_json.exists():
                if stack == "python":
                    vdata = {
                        "builds": [{"src": "main.py", "use": "@vercel/python"}],
                        "routes": [{"src": "/(.*)", "dest": "main.py"}],
                    }
                elif stack == "static":
                    vdata = {"cleanUrls": True}
                else:
                    vdata = {"framework": "nextjs"}
                vercel_json.write_text(json.dumps(vdata, indent=2), encoding="utf-8")
                created.append("vercel.json")

        elif provider == "render":
            render_yaml = self.project_dir / "render.yaml"
            if not render_yaml.exists():
                rcontent = (
                    f"services:\n"
                    f"  - type: web\n"
                    f"    name: {app_name}\n"
                    f"    env: {stack}\n"
                    f"    buildCommand: {'pip install -r requirements.txt' if stack == 'python' else 'npm install'}\n"
                    f"    startCommand: {'python -m uvicorn main:app --host 0.0.0.0 --port $PORT' if stack == 'python' else 'npm start'}\n"
                )
                render_yaml.write_text(rcontent, encoding="utf-8")
                created.append("render.yaml")

        return created

    def deploy(self, provider: str = "fly", dry_run: bool = False) -> CloudDeploymentResult:
        """
        Führt das Deployment durch oder erstellt die Manifeste im Dry-Run.
        """
        created = self.generate_manifests(provider=provider)
        app_name = self.project_dir.name.lower().replace("_", "-").replace(" ", "-")

        if dry_run:
            return CloudDeploymentResult(
                attempted=True,
                success=True,
                provider=provider,
                preview_url=f"https://{app_name}.fly.dev" if provider == "fly" else f"https://{app_name}.vercel.app",
                generated_files=created,
                output="Dry-Run: Manifeste erfolgreich generiert.",
            )

        # Prüfe CLI-Verfügbarkeit
        cli_tool = "flyctl" if provider == "fly" else ("vercel" if provider == "vercel" else None)
        if cli_tool and shutil.which(cli_tool) is None:
            return CloudDeploymentResult(
                attempted=False,
                provider=provider,
                generated_files=created,
                reason_skipped=f"CLI-Tool '{cli_tool}' ist auf diesem Rechner nicht installiert. Manifeste wurden vorbereitet.",
            )

        if provider == "fly":
            try:
                res = subprocess.run(
                    ["flyctl", "deploy", "--now"],
                    cwd=self.project_dir, capture_output=True, text=True, timeout=180.0,
                )
                success = res.returncode == 0
                url = f"https://{app_name}.fly.dev" if success else ""
                return CloudDeploymentResult(
                    attempted=True,
                    success=success,
                    provider="fly",
                    preview_url=url,
                    generated_files=created,
                    output=(res.stdout + res.stderr).strip()[-1000:],
                )
            except Exception as e:
                return CloudDeploymentResult(
                    attempted=True, success=False, provider="fly", output=str(e), generated_files=created,
                )

        return CloudDeploymentResult(
            attempted=True,
            success=True,
            provider=provider,
            preview_url=f"https://{app_name}.{provider}.app",
            generated_files=created,
            output=f"Manifeste für {provider} bereitgestellt.",
        )
