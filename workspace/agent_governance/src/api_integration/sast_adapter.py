import json
import logging
import subprocess
from typing import Any

from src.api_integration.schemas import SASTReport

# Konfiguration für SAST-Tools
SAST_CONFIG = {
    "bandit": {
        "command": ["bandit", "-f", "json", "-q", "-r"],
        "parser": lambda output: json.loads(output)
    }
}

class SASTAdapter:
    """
    Adapter für SAST-Tools wie Bandit zur Integration in die Governance-Plattform.
    """
    def __init__(self, tool: str = "bandit"):
        if tool not in SAST_CONFIG:
            raise ValueError(f"Tool {tool} nicht unterstützt.")
        self.tool = tool
        self.config = SAST_CONFIG[tool]
        self.logger = logging.getLogger(__name__)

    def run_analysis(self, target_path: str) -> SASTReport:
        """
        Führt die Analyse aus und normalisiert das Ergebnis.
        """
        cmd = self.config["command"] + [target_path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            # Bandit gibt bei Funden Exit-Code 1 zurück, daher nicht mit check=True arbeiten
            raw_data = self.config["parser"](result.stdout)
            return self._normalize(raw_data)
        except (json.JSONDecodeError, subprocess.SubprocessError) as e:
            self.logger.error(f"SAST Analyse fehlgeschlagen: {e}")
            return SASTReport(tool=self.tool, total_issues=0, issues=[], status="error", message=str(e))

    def _normalize(self, raw_data: dict[str, Any]) -> SASTReport:
        """
        Normalisiert Tool-spezifische Outputs in ein einheitliches Schema.
        """
        if self.tool == "bandit":
            results = raw_data.get("results", [])
            issues = [
                {
                    "severity": issue.get("issue_severity"),
                    "confidence": issue.get("issue_confidence"),
                    "file": issue.get("filename"),
                    "line": issue.get("line_number"),
                    "message": issue.get("test_name")
                } for issue in results
            ]
            return SASTReport(
                tool="bandit",
                total_issues=len(results),
                issues=issues,
                status="success"
            )
        return SASTReport(tool=self.tool, total_issues=0, issues=[], status="error", message="Unbekanntes Tool")
