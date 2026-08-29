"""
tests/test_structured_review_gate.py – Tests für strukturierte Review-Findings & Routing
"""

from core.review_gate import (
    ReviewFinding,
    parse_structured_findings,
    route_structured_findings,
)


def test_parse_structured_findings_json():
    content = """
Hier ist die Analyse:
```json
[
  {
    "severity": "critical",
    "file_path": "backend/auth.py",
    "line_number": 42,
    "title": "Hardcoded JWT Secret",
    "description": "Das Secret ist im Code hinterlegt.",
    "suggested_fix": "os.environ nutzen."
  },
  {
    "severity": "warning",
    "file_path": "frontend/App.tsx",
    "title": "Unused Import",
    "description": "Import von useState ungenutzt."
  }
]
```
"""
    findings = parse_structured_findings(content, source_role="security")
    assert len(findings) == 2
    assert findings[0].severity == "critical"
    assert findings[0].file_path == "backend/auth.py"
    assert findings[0].line_number == 42
    assert findings[0].source_role == "security"

    assert findings[1].severity == "warning"
    assert findings[1].file_path == "frontend/App.tsx"


def test_route_structured_findings():
    findings = [
        ReviewFinding(
            severity="critical",
            source_role="security",
            file_path="app/auth.py",
            title="SQL Injection",
        ),
        ReviewFinding(
            severity="critical",
            source_role="code_reviewer",
            file_path="unknown.py",
            title="Unmapped file",
        ),
    ]

    file_owners = {
        "app/auth.py": "backend",
        "frontend/src/App.vue": "frontend",
    }

    routed, unrouted = route_structured_findings(findings, file_owners)
    assert "backend" in routed
    assert len(routed["backend"]) == 1
    assert routed["backend"][0].title == "SQL Injection"
    assert len(unrouted) == 1
    assert unrouted[0].title == "Unmapped file"
