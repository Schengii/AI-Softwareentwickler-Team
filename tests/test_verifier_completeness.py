"""
tests/test_verifier_completeness.py – Testet den Vollständigkeits-Check
(core/verifier.py.check_completeness()).

Realer Fund (Bestandsaufnahme cloudvault-Projekt, siehe core/verifier/completeness.py): eine
Testsuite bestand vollständig, obwohl ein Endpunkt nur den Kommentar "Hier würde die
AES-256-GCM Verschlüsselung ... erfolgen" statt echter Verschlüsselung enthielt, und obwohl
das README auf eine nie generierte requirements.txt verwies. check_completeness() erkennt
beide Fälle.
"""

import tempfile
import unittest
from pathlib import Path

from core.verifier import ProjectVerifier


class TestCompletenessCheck(unittest.TestCase):
    def test_no_source_files_not_attempted(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.attempted)

    def test_clean_project_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.py").write_text(
                "def encrypt(data: bytes) -> bytes:\n    return real_aes_encrypt(data)\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.attempted)
            self.assertTrue(report.passed)
            self.assertEqual(report.issues, [])

    def test_detects_stub_comment(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.py").write_text(
                "async def upload_file(file):\n"
                "    # Hier würde die AES-256-GCM Verschlüsselung und S3-Speicherung erfolgen\n"
                "    return {'id': 1}\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.attempted)
            self.assertFalse(report.passed)
            self.assertEqual(len(report.issues), 1)
            self.assertEqual(report.issues[0].file_path, "app.py")
            self.assertEqual(report.issues[0].line_number, 2)

    def test_detects_not_implemented_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "auth.py").write_text(
                "def verify_token(token):\n    raise NotImplementedError\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertEqual(len(report.issues), 1)

    def test_detects_elided_code_comment(self):
        # Achter realer Fund (mockforge-Projekt, Team-Retrospektive 2026-09-05): ein Agent
        # ersetzte den kompletten Funktionskörper durch elidierte Kommentarzeilen
        # ("# ... (Imports)", "# ... (Request-Handling)") statt echten Code - syntaktisch
        # gueltige Kommentare, die aber alle darunter liegenden Namen undefiniert
        # zurueckliessen. Nur ruff (F821 in einer separaten CI-Pruefung) fing das zufaellig ab.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "middleware.py").write_text(
                "# ... (Imports)\n"
                "class ProxyMiddleware:\n"
                "    async def dispatch(self, request, call_next):\n"
                "        # ... (Request-Handling)\n"
                "        response = await call_next(request)\n"
                "        return response\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertEqual(len(report.issues), 2)

    def test_ellipsis_inside_normal_comment_not_flagged(self):
        # Ein legitimer Kommentar, der zufaellig "..." enthaelt, aber danach noch Fliesstext
        # hat, ist kein elidierter Code - bewusst kein Fehlalarm.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.py").write_text(
                "def load():\n    x = 1  # loads data ... slowly, but correctly\n    return x\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_detects_missing_readme_referenced_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")
            (project_dir / "README.md").write_text(
                "## Setup\n```bash\npip install -r requirements.txt\n```\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("requirements.txt" in i.message for i in report.issues))

    def test_existing_readme_referenced_file_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")
            (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            (project_dir / "README.md").write_text(
                "## Setup\n```bash\npip install -r requirements.txt\n```\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_detects_write_route_without_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI\n"
                "app = FastAPI()\n\n"
                "@app.post('/api/v1/files/upload')\n"
                "async def upload_file(file):\n"
                "    return {'id': 1, 'filename': file.filename}\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("I/O" in i.message for i in report.issues))

    def test_write_route_with_io_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI\n"
                "app = FastAPI()\n\n"
                "@app.post('/api/v1/files/upload')\n"
                "async def upload_file(file):\n"
                "    result = await db.execute(insert(File).values(name=file.filename))\n"
                "    return {'id': result.id}\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_write_route_exempt_name_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI\n"
                "app = FastAPI()\n\n"
                "@app.post('/api/v1/logout')\n"
                "async def logout():\n"
                "    return {'ok': True}\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_detects_component_without_props_or_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "Dashboard.js").write_text(
                "import React from 'react';\n"
                "const Dashboard = () => {\n"
                "  return (\n"
                "    <div><p>1.2 GB</p></div>\n"
                "  );\n"
                "};\n"
                "export default Dashboard;\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("Dashboard.js" in i.file_path for i in report.issues))

    def test_component_with_api_call_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "Dashboard.js").write_text(
                "import React, { useEffect, useState } from 'react';\n"
                "const Dashboard = () => {\n"
                "  const [data, setData] = useState(null);\n"
                "  useEffect(() => { fetch('/api/v1/stats').then(r => r.json()).then(setData); }, []);\n"
                "  return (\n"
                "    <div><p>{data}</p></div>\n"
                "  );\n"
                "};\n"
                "export default Dashboard;\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_component_with_props_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "Dashboard.js").write_text(
                "import React from 'react';\n"
                "const Dashboard = ({ stats }) => {\n"
                "  return (\n"
                "    <div><p>{stats.storage}</p></div>\n"
                "  );\n"
                "};\n"
                "export default Dashboard;\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_detects_missing_dependency_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI\nfrom pydantic import BaseModel\napp = FastAPI()\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("Dependency-Manifest" in i.message for i in report.issues))

    def test_local_imports_not_flagged_as_missing_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            (app_dir / "main.py").write_text("app = object()\n", encoding="utf-8")
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_app.py").write_text(
                "from app.main import app\n\ndef test_app():\n    assert app\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_manifest_present_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_detects_missing_relative_import_sibling(self):
        # Realer Fund (taskpulse-Projekt): `from . import database, models, schemas` in
        # app/main.py, aber app/models.py wurde nie angelegt.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            (app_dir / "database.py").write_text("engine = None\n", encoding="utf-8")
            (app_dir / "schemas.py").write_text("class Task: pass\n", encoding="utf-8")
            (app_dir / "main.py").write_text(
                "from . import database, models, schemas\n\napp = object()\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("models" in i.message and "app/main.py" == i.file_path for i in report.issues))

    def test_detects_missing_relative_submodule_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            (app_dir / "main.py").write_text(
                "from .core.config import settings\n\napp = object()\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("core/config" in i.message for i in report.issues))

    def test_existing_relative_imports_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            (app_dir / "database.py").write_text("engine = None\n", encoding="utf-8")
            (app_dir / "models.py").write_text("class Task: pass\n", encoding="utf-8")
            (app_dir / "schemas.py").write_text("class TaskSchema: pass\n", encoding="utf-8")
            core_dir = app_dir / "core"
            core_dir.mkdir()
            (core_dir / "__init__.py").write_text("", encoding="utf-8")
            (core_dir / "config.py").write_text("settings = object()\n", encoding="utf-8")
            (app_dir / "main.py").write_text(
                "from . import database, models, schemas\n"
                "from .core.config import settings\n\napp = object()\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_detects_missing_symbol_in_existing_module_file(self):
        # Team-Optimierung (Retrospektive 2026-09-04, sechster realer Fund): real beobachtet an
        # `zeiterfassung_app` - app/main.py importierte `RateLimitMiddleware`, die Klasse in der
        # Zieldatei hieß aber tatsächlich `SimpleRateLimiter`. Die Zieldatei EXISTIERT (anders
        # als beim taskpulse-Fund oben), der Import schlägt trotzdem mit ImportError fehl.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            middleware_dir = app_dir / "middleware"
            middleware_dir.mkdir()
            (middleware_dir / "__init__.py").write_text("", encoding="utf-8")
            (middleware_dir / "rate_limit.py").write_text(
                "class SimpleRateLimiter:\n    pass\n", encoding="utf-8",
            )
            (app_dir / "main.py").write_text(
                "from .middleware.rate_limit import RateLimitMiddleware\n\napp = object()\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any(
                "RateLimitMiddleware" in i.message and "rate_limit.py" in i.message
                for i in report.issues
            ))
            # Team-Optimierung (vollständige Umsetzung einer KI-Team-Retrospektive, echter Fund
            # am event_relay-Lauf 2026-09-06): agents/orchestrator/verification.py filterte
            # genau diese Fund-Klasse bisher per Substring-Suche `"existierendes lokales" in
            # message` heraus, um sie VOR jedem Testlauf UND in den Governance-Fix-Prompt
            # einzuspeisen - diese Meldung enthält die Zeichenfolge aber NIE ("... definiertes/
            # importiertes Symbol"), der Fund fiel dadurch trotz korrekter Erkennung hier durch
            # beide Filter. `kind="missing_local_import"` ist das stabile Ersatz-Tag dafür.
            self.assertTrue(any(
                i.kind == "missing_local_import" and "RateLimitMiddleware" in i.message
                for i in report.issues
            ))

    def test_existing_symbol_in_module_file_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            middleware_dir = app_dir / "middleware"
            middleware_dir.mkdir()
            (middleware_dir / "__init__.py").write_text("", encoding="utf-8")
            (middleware_dir / "rate_limit.py").write_text(
                "class RateLimitMiddleware:\n    pass\n", encoding="utf-8",
            )
            (app_dir / "main.py").write_text(
                "from .middleware.rate_limit import RateLimitMiddleware\n\napp = object()\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_reexported_symbol_via_plain_import_in_module_file_not_flagged(self):
        # `defined` erfasst auch Namen, die die Zieldatei selbst importiert (Re-Export) - z.B.
        # `from .base import RateLimiter as RateLimitMiddleware` in rate_limit.py.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            middleware_dir = app_dir / "middleware"
            middleware_dir.mkdir()
            (middleware_dir / "__init__.py").write_text("", encoding="utf-8")
            (middleware_dir / "base.py").write_text("class RateLimiter:\n    pass\n", encoding="utf-8")
            (middleware_dir / "rate_limit.py").write_text(
                "from .base import RateLimiter as RateLimitMiddleware\n", encoding="utf-8",
            )
            (app_dir / "main.py").write_text(
                "from .middleware.rate_limit import RateLimitMiddleware\n\napp = object()\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_wildcard_import_in_module_file_suppresses_symbol_check(self):
        # Ein Wildcard-Import in der Zieldatei kann beliebige Namen einführen - eine rein
        # statische Analyse kann das nicht zuverlässig auflösen, also lieber gar nicht melden
        # als einen Fehlalarm riskieren.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            (app_dir / "constants.py").write_text("SOME_OTHER_VALUE = 1\n", encoding="utf-8")
            (app_dir / "settings.py").write_text("from .constants import *\n", encoding="utf-8")
            (app_dir / "main.py").write_text(
                "from .settings import ANYTHING_AT_ALL\n\napp = object()\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_dynamic_getattr_in_module_file_suppresses_symbol_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            (app_dir / "dynamic.py").write_text(
                "def __getattr__(name):\n    return object()\n", encoding="utf-8",
            )
            (app_dir / "main.py").write_text(
                "from .dynamic import AnythingGeneratedAtRuntime\n\napp = object()\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_reexported_symbol_via_init_not_flagged(self):
        # "from . import X" ist mehrdeutig: X kann ein Submodul ODER ein in __init__.py
        # (re-)exportiertes Symbol sein - Letzteres ist kein Fehler.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("CONFIG_VALUE = 42\n", encoding="utf-8")
            (app_dir / "main.py").write_text(
                "from . import CONFIG_VALUE\n\napp = object()\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_missing_absolute_local_package_import_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            (app_dir / "main.py").write_text("app = object()\n", encoding="utf-8")
            (project_dir / "run.py").write_text(
                "from app import models\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("run.py" == i.file_path for i in report.issues))

    def test_detects_missing_relative_js_import(self):
        # JS/TS-Pendant zum taskpulse-Fund: `import { formatDate } from './utils/date'`, aber
        # utils/date.js wurde nie angelegt.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.js").write_text(
                "import { formatDate } from './utils/date';\nconsole.log(formatDate());\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("utils/date" in i.message and i.file_path == "app.js" for i in report.issues))

    def test_existing_relative_js_import_with_extension_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            utils_dir = project_dir / "utils"
            utils_dir.mkdir()
            (utils_dir / "date.js").write_text("export function formatDate() { return '2026'; }\n", encoding="utf-8")
            (project_dir / "app.js").write_text(
                "import { formatDate } from './utils/date';\nconsole.log(formatDate());\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_existing_relative_js_index_import_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            utils_dir = project_dir / "utils"
            utils_dir.mkdir()
            (utils_dir / "index.ts").write_text("export const x = 1;\n", encoding="utf-8")
            (project_dir / "app.ts").write_text(
                "import { x } from './utils';\nconsole.log(x);\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_missing_js_require_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "server.js").write_text(
                "const db = require('./db/connection');\nmodule.exports = db;\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("db/connection" in i.message for i in report.issues))

    def test_non_js_extension_relative_import_not_flagged(self):
        # Asset-/CSS-/JSON-Importe hängen von der Bundler-Konfiguration ab - bewusst NICHT
        # geprüft (siehe _JS_MODULE_EXTENSIONS-Docstring in core/verifier/models.py).
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "App.jsx").write_text(
                "import './styles.css';\nimport logo from './logo.svg';\n"
                "export default function App() { return null; }\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_npm_package_import_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.js").write_text(
                "import React from 'react';\nimport { useState } from 'react';\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_detects_js_write_route_without_io(self):
        # JS/TS-Pendant zum cloudvault-Fund: ein Express-Handler mit hartcodierter
        # Literal-Rückgabe statt echter Persistenz.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "server.js").write_text(
                "const express = require('express');\nconst app = express();\n\n"
                "app.post('/api/v1/files/upload', (req, res) => {\n"
                "  res.json({ id: 1, filename: req.body.filename });\n"
                "});\n",
                encoding="utf-8",
            )
            (project_dir / "package.json").write_text("{}\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("I/O" in i.message and i.file_path == "server.js" for i in report.issues))

    def test_js_write_route_with_io_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "server.js").write_text(
                "app.post('/api/v1/files/upload', async (req, res) => {\n"
                "  const result = await db.collection('files').insertOne(req.body);\n"
                "  res.json({ id: result.insertedId });\n"
                "});\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_js_write_route_exempt_path_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "server.js").write_text(
                "app.post('/api/v1/logout', (req, res) => {\n"
                "  res.clearCookie('session');\n"
                "  res.json({ ok: true });\n"
                "});\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_js_write_route_named_handler_reference_not_flagged(self):
        # "app.post('/x', createUser)" referenziert eine BENANNTE Funktion (kein Inline-Handler
        # an dieser Stelle) - bewusst nicht geprüft, siehe Docstring von
        # _scan_js_write_routes_missing_io() in core/verifier/completeness.py.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "server.js").write_text(
                "function createUser(req, res) {\n  res.json({ id: 1 });\n}\n\n"
                "app.post('/api/v1/users', createUser);\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_detects_missing_known_package_in_manifest(self):
        # Siebter realer Fund (logpulse-Projekt): requirements.txt existiert, listet aber
        # `httpx` nicht auf, obwohl tests/conftest.py es importiert.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_app.py").write_text(
                "from httpx import AsyncClient\n\ndef test_x():\n    pass\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("httpx" in i.message for i in report.issues))

    def test_transitive_fastapi_dependencies_not_flagged(self):
        # Fehlalarm-Regressionstest (Live-Abgleich gegen alle workspace/-Projekte, Team-
        # Retrospektive 2026-09-05): `starlette`/`pydantic` sind Pflicht-Abhängigkeiten von
        # `fastapi` selbst - `pip install fastapi` installiert sie immer automatisch mit, ein
        # direkter Import ohne eigenen requirements.txt-Eintrag ist deshalb kein echter Fund.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI\n"
                "from starlette.requests import Request\n"
                "from pydantic import BaseModel\n"
                "app = FastAPI()\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_transitive_flask_typer_dependencies_not_flagged(self):
        # Dasselbe Prinzip wie oben, nur fuer `jinja2` (Pflicht-Abhaengigkeit von `flask`) und
        # `click` (Pflicht-Abhaengigkeit von `typer`/`uvicorn[standard]`).
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.py").write_text(
                "from flask import Flask\n"
                "from jinja2 import Template\n"
                "import click\n"
                "app = Flask(__name__)\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("flask\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_known_package_present_in_manifest_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\nhttpx\n", encoding="utf-8")
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_app.py").write_text(
                "from httpx import AsyncClient\n\ndef test_x():\n    pass\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_detects_missing_pytest_asyncio_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text(
                "fastapi\npytest\nhttpx\n", encoding="utf-8",
            )
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_app.py").write_text(
                "import pytest\n\n"
                "@pytest.mark.asyncio\n"
                "async def test_x():\n    assert True\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("pytest-asyncio" in i.message for i in report.issues))

    def test_pytest_asyncio_present_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text(
                "fastapi\npytest\npytest-asyncio\nhttpx\n", encoding="utf-8",
            )
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_app.py").write_text(
                "import pytest\n\n"
                "@pytest.mark.asyncio\n"
                "async def test_x():\n    assert True\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_sync_test_without_asyncio_mark_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\npytest\n", encoding="utf-8")
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_app.py").write_text(
                "def test_x():\n    assert True\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_detects_mixed_sync_and_async_sqlalchemy_engines(self):
        # Achter realer Fund (logpulse-Projekt): app/database.py definiert eine asynchrone
        # Engine, app/models.py daneben eine eigene synchrone Engine + eigene Base.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            (app_dir / "database.py").write_text(
                "from sqlalchemy.ext.asyncio import create_async_engine\n"
                "from sqlalchemy.orm import declarative_base\n"
                "engine = create_async_engine('sqlite+aiosqlite:///./x.db')\n"
                "Base = declarative_base()\n",
                encoding="utf-8",
            )
            (app_dir / "models.py").write_text(
                "from sqlalchemy import create_engine\n"
                "from sqlalchemy.orm import declarative_base\n"
                "engine = create_engine('sqlite:///./x.db')\n"
                "Base = declarative_base()\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("sqlalchemy\naiosqlite\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("create_async_engine" in i.message for i in report.issues))
            self.assertTrue(any("declarative_base" in i.message for i in report.issues))

    def test_alembic_context_import_not_flagged_as_missing_local_module(self):
        # Fehlalarm-Regressionstest (Live-Abgleich gegen alle workspace/-Projekte, Team-
        # Retrospektive 2026-09-05, real beobachtet an `fastapi-task-mgmt`): das lokale
        # `alembic/`-Migrationsverzeichnis kollidiert im Namen mit dem PyPI-Paket `alembic`.
        # `from alembic import context` meint das ECHTE, pip-installierte Paket (context wird
        # von Alembic selbst zur Laufzeit injiziert), nicht das lokale Verzeichnis.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            alembic_dir = project_dir / "alembic"
            alembic_dir.mkdir()
            (alembic_dir / "env.py").write_text(
                "from alembic import context\ncontext.run_migrations_online()\n", encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("alembic\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_alembic_sync_engine_alongside_async_app_not_flagged(self):
        # Fehlalarm-Regressionstest (Live-Abgleich gegen alle workspace/-Projekte, Team-
        # Retrospektive 2026-09-05, real beobachtet an `fastapi-task-mgmt`): alembic/env.py
        # nutzt idiomatisch eine synchrone create_engine() fuer den Migrationslauf, selbst wenn
        # die App durchgehend async ist - das ist Standardpraxis, kein Bug.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            (app_dir / "database.py").write_text(
                "from sqlalchemy.ext.asyncio import create_async_engine\n"
                "engine = create_async_engine('sqlite+aiosqlite:///./x.db')\n",
                encoding="utf-8",
            )
            alembic_dir = project_dir / "alembic"
            alembic_dir.mkdir()
            (alembic_dir / "env.py").write_text(
                "from sqlalchemy import create_engine\n"
                "connectable = create_engine('sqlite:///./x.db')\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("sqlalchemy\naiosqlite\nalembic\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_single_sqlalchemy_base_and_engine_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            (app_dir / "database.py").write_text(
                "from sqlalchemy.ext.asyncio import create_async_engine\n"
                "from sqlalchemy.orm import declarative_base\n"
                "engine = create_async_engine('sqlite+aiosqlite:///./x.db')\n"
                "Base = declarative_base()\n",
                encoding="utf-8",
            )
            (app_dir / "models.py").write_text(
                "from app.database import Base\n"
                "from sqlalchemy import Column, Integer\n"
                "class Item(Base):\n"
                "    __tablename__ = 'items'\n"
                "    id = Column(Integer, primary_key=True)\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("sqlalchemy\naiosqlite\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_detects_double_router_prefix(self):
        # Neunter realer Fund (logpulse-Projekt): app/routers/logs.py deklariert bereits
        # APIRouter(prefix="/api/v1/logs"), app/main.py hängt beim Registrieren zusätzlich
        # prefix="/api/v1" an - die Route landet unter /api/v1/api/v1/logs statt /api/v1/logs.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            routers_dir = app_dir / "routers"
            routers_dir.mkdir()
            (routers_dir / "__init__.py").write_text("", encoding="utf-8")
            (routers_dir / "logs.py").write_text(
                "from fastapi import APIRouter\n"
                "router = APIRouter(prefix='/api/v1/logs', tags=['logs'])\n\n"
                "@router.get('')\n"
                "async def read_logs():\n    return []\n",
                encoding="utf-8",
            )
            (app_dir / "main.py").write_text(
                "from fastapi import FastAPI\n"
                "from app.routers import logs\n\n"
                "app = FastAPI()\n"
                "app.include_router(logs.router, prefix='/api/v1', tags=['logs'])\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any(
                "/api/v1/api/v1/logs" in i.message and i.file_path == "app/main.py"
                for i in report.issues
            ))

    def test_single_router_prefix_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            routers_dir = app_dir / "routers"
            routers_dir.mkdir()
            (routers_dir / "__init__.py").write_text("", encoding="utf-8")
            (routers_dir / "logs.py").write_text(
                "from fastapi import APIRouter\n"
                "router = APIRouter(prefix='/api/v1/logs', tags=['logs'])\n\n"
                "@router.get('')\n"
                "async def read_logs():\n    return []\n",
                encoding="utf-8",
            )
            (app_dir / "main.py").write_text(
                "from fastapi import FastAPI\n"
                "from app.routers import logs\n\n"
                "app = FastAPI()\n"
                "app.include_router(logs.router)\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_detects_missing_sqlalchemy_dsn_driver_package(self):
        # Zehnter realer Fund (incidentpilot-Projekt): die DSN "postgresql+asyncpg://..." nennt
        # ihren Treiber nur als String-Literal - SQLAlchemy lädt ihn erst zur Laufzeit anhand
        # des Schemas nach, es gibt nie ein statisches "import asyncpg". requirements.txt
        # listete stattdessen nur den SYNCHRONEN Treiber `psycopg2-binary`.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            (app_dir / "database.py").write_text(
                "import os\n"
                "DATABASE_URL = os.getenv('DATABASE_URL', "
                "'postgresql+asyncpg://user:pw@localhost/db')\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text(
                "fastapi\nsqlalchemy\npsycopg2-binary\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("asyncpg" in i.message for i in report.issues))

    def test_sqlalchemy_dsn_driver_present_in_manifest_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            (app_dir / "database.py").write_text(
                "DATABASE_URL = 'postgresql+asyncpg://user:pw@localhost/db'\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text(
                "fastapi\nsqlalchemy\nasyncpg\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_sqlite_dsn_driver_message_names_correct_scheme(self):
        # Regressionstest für einen Fehlalarm in der ersten Fassung dieses Checks: die
        # Meldung hardcodierte "postgresql+<treiber>" unabhängig vom tatsächlichen Schema.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            (app_dir / "database.py").write_text(
                "DATABASE_URL = 'sqlite+aiosqlite:///./x.db'\n", encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\nsqlalchemy\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            issue = next(i for i in report.issues if "aiosqlite" in i.message)
            self.assertIn("sqlite+aiosqlite://", issue.message)
            self.assertNotIn("postgresql+aiosqlite", issue.message)

    def test_write_route_with_multiline_signature_and_background_task_not_flagged(self):
        # Zwölfter realer Fund (incidentpilot-Projekt): eine mehrzeilige Funktionssignatur mit
        # uneingerückter schließender "):"-Zeile ließ die Body-Erfassung abbrechen, bevor der
        # eigentliche Funktionskörper (hier: Persistenz per `background_tasks.add_task(...)`,
        # ein etabliertes FastAPI-Idiom) je gescannt wurde.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI, BackgroundTasks, Header\n"
                "app = FastAPI()\n\n"
                "def save_incident(event_type, payload):\n"
                "    pass\n\n"
                "@app.post('/webhooks/receive')\n"
                "async def receive_webhook(\n"
                "    background_tasks: BackgroundTasks,\n"
                "    x_signature: str = Header(None)\n"
                "):\n"
                "    \"\"\"Empfaengt Webhooks.\"\"\"\n"
                "    background_tasks.add_task(save_incident, 'x', {})\n"
                "    return {'status': 'accepted'}\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_write_route_with_multiline_signature_and_no_io_still_flagged(self):
        # Gegenprobe: eine mehrzeilige Signatur darf den Check nicht komplett abschalten -
        # ein Handler ohne jeden I/O-Aufruf muss weiterhin gemeldet werden.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI, Header\n"
                "app = FastAPI()\n\n"
                "@app.post('/webhooks/receive')\n"
                "async def receive_webhook(\n"
                "    x_signature: str = Header(None)\n"
                "):\n"
                "    return {'status': 'accepted'}\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("receive_webhook" in i.message for i in report.issues))

    def test_ignores_venv_and_node_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")
            venv_dir = project_dir / ".ai_team_venv" / "lib"
            venv_dir.mkdir(parents=True)
            (venv_dir / "dep.py").write_text("# Hier würde das erfolgen\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)


if __name__ == "__main__":
    unittest.main()
