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
from core.verifier.models import _SQLA_DSN_DRIVER_RE


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

    def test_write_route_with_named_remove_method_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI\n"
                "app = FastAPI()\n\n"
                "@app.delete('/api/v1/alerts/{rule_id}')\n"
                "async def delete_alert_rule(rule_id: str):\n"
                "    removed = alert_engine.remove_rule(rule_id)\n"
                "    return {'status': 'deleted', 'id': rule_id}\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_write_route_with_named_delete_or_clear_method_passes(self):
        """Team-Optimierung 2026-09-17 (hyperion_metrics-Root-Cause): `.delete...(`/`.clear...(`
        auf einer In-Memory-Engine ist dieselbe Klasse valider Zustandsmutation wie `.remove...(`/
        `.pop(` und darf nicht als fehlender I/O gemeldet werden."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI\n"
                "app = FastAPI()\n\n"
                "@app.delete('/api/v1/alerts/{rule_id}')\n"
                "async def delete_alert_rule(rule_id: str):\n"
                "    removed = alert_engine.delete_rule(rule_id)\n"
                "    return {'status': 'deleted', 'id': rule_id}\n\n"
                "@app.post('/api/v1/cache/flush')\n"
                "async def flush_cache():\n"
                "    cache_store.clear_all()\n"
                "    return {'status': 'flushed'}\n",
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

    def test_ensure_environment_deterministically_scaffolds_pytest_asyncio_in_manifest(self):
        # Team-Optimierung (NexusForge-Lauf, Schwachstelle 3): ensure_environment() sicherte
        # bisher nur die SANDBOX-Laufzeit ab (pip install pytest-asyncio) - requirements.txt
        # selbst blieb unverändert, wodurch der obige _missing_async_test_dependencies()-Fund
        # weiterhin auftrat, obwohl die Tests in der Sandbox längst grün liefen. Nach
        # ensure_environment() muss `pytest-asyncio` deshalb auch physisch im Manifest stehen,
        # UND der anschließende check_completeness()-Lauf muss dadurch grün werden.
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
            verifier._ensure_async_test_manifest_entry()

            # Test-Plugins gehören in requirements-dev.txt, nicht in die Produktions-Abhängigkeiten.
            dev_manifest = (project_dir / "requirements-dev.txt").read_text(encoding="utf-8")
            self.assertIn("pytest-asyncio", dev_manifest)
            manifest = (project_dir / "requirements.txt").read_text(encoding="utf-8")
            self.assertNotIn("pytest-asyncio", manifest)
            # Bereits vorhandene Einträge dürfen nicht verloren gehen.
            self.assertIn("fastapi", manifest)

            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_ensure_async_test_manifest_entry_skips_when_anyio_already_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "requirements.txt").write_text("fastapi\nanyio\n", encoding="utf-8")
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_app.py").write_text(
                "async def test_x():\n    assert True\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            log = verifier._ensure_async_test_manifest_entry()

            self.assertEqual(log, "")
            manifest = (project_dir / "requirements.txt").read_text(encoding="utf-8")
            self.assertNotIn("pytest-asyncio", manifest)

    def test_ensure_async_test_manifest_entry_noop_without_requirements_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_app.py").write_text(
                "async def test_x():\n    assert True\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            log = verifier._ensure_async_test_manifest_entry()

            self.assertEqual(log, "")
            self.assertFalse((project_dir / "requirements.txt").exists())

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
            (project_dir / "requirements.txt").write_text(
                "sqlalchemy\naiosqlite\nalembic\ngreenlet\n", encoding="utf-8",
            )
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
            (project_dir / "requirements.txt").write_text("sqlalchemy\naiosqlite\ngreenlet\n", encoding="utf-8")
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

    def test_sqla_dsn_driver_regex_matches_variable_slash_count(self):
        # HyperionSentinel-Fund (2026-09-13): SQLite-DSNs verwenden 3 Slashes bei relativen
        # ("sqlite+aiosqlite:///./x.db") und 4 Slashes bei absoluten Pfaden
        # ("sqlite+aiosqlite:////abs/x.db"), waehrend Postgres/MySQL-DSNs klassisch nur 2
        # Slashes ("postgresql+asyncpg://host/db") verwenden. Die Regex muss alle drei Faelle
        # erkennen und den Treibernamen korrekt extrahieren.
        self.assertEqual(
            _SQLA_DSN_DRIVER_RE.findall("DATABASE_URL = 'postgresql+asyncpg://user:pw@host/db'"),
            [("postgresql+asyncpg", "asyncpg")],
        )
        self.assertEqual(
            _SQLA_DSN_DRIVER_RE.findall("DATABASE_URL = 'sqlite+aiosqlite:///./x.db'"),
            [("sqlite+aiosqlite", "aiosqlite")],
        )
        self.assertEqual(
            _SQLA_DSN_DRIVER_RE.findall("DATABASE_URL = 'sqlite+aiosqlite:////abs/pfad/x.db'"),
            [("sqlite+aiosqlite", "aiosqlite")],
        )

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

    def test_detects_missing_aiosqlite_with_absolute_path_dsn_four_slashes(self):
        # HyperionSentinel-Fund (2026-09-13): ein absoluter SQLite-Pfad verwendet VIER Slashes
        # (`sqlite+aiosqlite:////abs/pfad/x.db`) statt der drei Slashes bei relativen Pfaden -
        # `_SQLA_DSN_DRIVER_RE` muss eine variable Slash-Anzahl (2 bis 4) akzeptieren.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            app_dir = project_dir / "app"
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            (app_dir / "database.py").write_text(
                "DATABASE_URL = 'sqlite+aiosqlite:////abs/pfad/x.db'\n", encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\nsqlalchemy\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("aiosqlite" in i.message for i in report.issues))

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

    def test_detects_trusted_host_wildcard(self):
        # Elfter realer Fund (taskboard-Projekt): TrustedHostMiddleware(allowed_hosts=["*"])
        # erlaubt jeden Host-Header und hebelt den Schutz vor Host-Header-Injection aus.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI\n"
                "from fastapi.middleware.trustedhost import TrustedHostMiddleware\n"
                "app = FastAPI()\n"
                "app.add_middleware(TrustedHostMiddleware, allowed_hosts=[\"*\"])\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("TrustedHostMiddleware" in i.message for i in report.issues))

    def test_trusted_host_with_explicit_domains_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI\n"
                "from fastapi.middleware.trustedhost import TrustedHostMiddleware\n"
                "app = FastAPI()\n"
                "app.add_middleware(TrustedHostMiddleware, allowed_hosts=[\"example.com\"])\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_detects_cors_wildcard_with_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI\n"
                "from fastapi.middleware.cors import CORSMiddleware\n"
                "app = FastAPI()\n"
                "app.add_middleware(\n"
                "    CORSMiddleware,\n"
                "    allow_origins=[\"*\"],\n"
                "    allow_credentials=True,\n"
                ")\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("CORSMiddleware" in i.message for i in report.issues))

    def test_cors_wildcard_without_credentials_not_flagged(self):
        # Oeffentliche, nicht-authentifizierte APIs mit reinem Wildcard-CORS (ohne Credentials)
        # sind gaengige, unbedenkliche Praxis - bewusst nicht gemeldet.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from fastapi import FastAPI\n"
                "from fastapi.middleware.cors import CORSMiddleware\n"
                "app = FastAPI()\n"
                "app.add_middleware(CORSMiddleware, allow_origins=[\"*\"])\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

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

    def test_detects_missing_greenlet_dependency(self):
        # Team-Optimierung (Retrospektive 2026-09-08, logpulse-Fund vom 2026-09-05): async
        # SQLAlchemy-Engine braucht `greenlet` zur Laufzeit, obwohl der Code es nirgends
        # importiert - fehlt es im Manifest, muss das gemeldet werden.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "database.py").write_text(
                "from sqlalchemy.ext.asyncio import create_async_engine\n"
                "engine = create_async_engine('sqlite+aiosqlite:///./x.db')\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text("sqlalchemy\naiosqlite\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("greenlet" in i.message for i in report.issues))

    def test_greenlet_present_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "database.py").write_text(
                "from sqlalchemy.ext.asyncio import create_async_engine\n"
                "engine = create_async_engine('sqlite+aiosqlite:///./x.db')\n",
                encoding="utf-8",
            )
            (project_dir / "requirements.txt").write_text(
                "sqlalchemy\naiosqlite\ngreenlet\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_detects_resilience_fallback_dict_type_mismatch(self):
        # Team-Optimierung (Retrospektive 2026-09-08, opspilot-Fund): der Fallback-Zweig eines
        # Circuit-Breaker-Except-Blocks liefert ein rohes dict statt des vom Aufrufer erwarteten
        # Pydantic-Modells zurück.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "resilience.py").write_text(
                "def resilience_wrapper(func):\n"
                "    def wrapper(*args, **kwargs):\n"
                "        try:\n"
                "            return func(*args, **kwargs)\n"
                "        except CircuitBreakerError:\n"
                "            return {\"status\": \"fallback\", \"reason\": \"circuit_open\"}\n"
                "    return wrapper\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("dict" in i.message and "Circuit" in i.message for i in report.issues))

    def test_resilience_fallback_raising_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "resilience.py").write_text(
                "def resilience_wrapper(func):\n"
                "    def wrapper(*args, **kwargs):\n"
                "        try:\n"
                "            return func(*args, **kwargs)\n"
                "        except CircuitBreakerError:\n"
                "            logger.warning('circuit open')\n"
                "            raise\n"
                "    return wrapper\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_detects_direct_dict_return_type_mismatch(self):
        # Team-Optimierung (KI-Team-Weiterentwicklung, echter Fund: agent_governance-Projekt,
        # 2026-09-09) - `SASTAdapter.scan()` ist annotiert, ein `SASTReport`-Objekt
        # zurückzugeben, liefert aber ein rohes Dict-Literal, OHNE dass ein Resilience-/
        # Circuit-Breaker-Except-Block beteiligt ist (siehe test_detects_resilience_fallback_
        # dict_type_mismatch oben für das verwandte, aber enger gefasste Muster).
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "sast_adapter.py").write_text(
                "class SASTAdapter:\n"
                "    def scan(self, target: str) -> SASTReport:\n"
                "        return {\"findings\": [], \"target\": target}\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any(
                "SASTReport" in i.message and "scan" in i.message for i in report.issues
            ))

    def test_direct_dict_return_matching_annotation_not_flagged(self):
        # Gegen-Test: Rückgabetyp-Annotation ist bereits `dict` - ein Dict-Literal ist dann
        # genau das Erwartete, kein Fund.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "adapter.py").write_text(
                "def scan(target: str) -> dict:\n"
                "    return {\"findings\": [], \"target\": target}\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_direct_dict_return_constructing_model_not_flagged(self):
        # Gegen-Test: die Funktion konstruiert tatsächlich eine Instanz des annotierten Typs -
        # kein Dict-Literal, kein Fund.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "adapter.py").write_text(
                "class SASTAdapter:\n"
                "    def scan(self, target: str) -> SASTReport:\n"
                "        return SASTReport(findings=[], target=target)\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_direct_dict_return_nested_function_not_flagged(self):
        # Gegen-Test: das Dict-Literal steht in einer VERSCHACHTELTEN inneren Funktion mit
        # eigener, unabhängiger Signatur - die äußere Funktion selbst gibt kein Dict zurück.
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "adapter.py").write_text(
                "def build_report(target: str) -> SASTReport:\n"
                "    def _to_payload() -> dict:\n"
                "        return {\"target\": target}\n"
                "    return SASTReport(**_to_payload())\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    # ── ChronosPulse-Analyse (20260913), Empfehlung 3: Pseudocode-/Auszugs-Stubs ──

    def test_detects_auszug_aus_marker(self):
        """Realer Fund: `app/utils/resilience.py` bestand nur aus einem "# Auszug aus..."-
        Kommentar statt der eigentlichen CircuitBreaker-/ExponentialBackoff-Implementierung."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "resilience.py").write_text(
                "# Auszug aus app/utils/resilience.py\n"
                "# - CircuitBreaker: Statusverwaltung (CLOSED, OPEN, HALF_OPEN)\n"
                "# - ExponentialBackoff: Full-Jitter mit secrets.SystemRandom()\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.attempted)
            self.assertFalse(report.passed)
            messages = " ".join(i.message for i in report.issues)
            self.assertIn("Auszug", messages)

    def test_detects_implementierungsbeispiel_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "auth.py").write_text(
                "def check_permission(user, resource) -> bool:\n"
                "    # Implementierungsbeispiel - echte RBAC-Prüfung folgt\n"
                "    return True\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)

    def test_comment_only_file_flagged_as_stub(self):
        """Strukturelle Gegenprobe zum Text-Marker oben: eine Datei, die NUR aus Kommentaren
        besteht (kein Code-Statement), muss auch OHNE einen bekannten Marker-Text erkannt
        werden - die exakte real beobachtete resilience.py hatte 5 Zeilen reinen Kommentar."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "resilience.py").write_text(
                "# CircuitBreaker verwaltet CLOSED/OPEN/HALF_OPEN-Status\n"
                "# ExponentialBackoff nutzt Full-Jitter\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.attempted)
            self.assertFalse(report.passed)
            self.assertTrue(
                any("Kommentarzeile" in i.message for i in report.issues),
                report.issues,
            )

    def test_comment_only_file_above_line_threshold_not_flagged(self):
        """Über der Zeilenschwelle (_COMMENT_ONLY_STUB_MAX_LINES) handelt es sich eher um eine
        legitime, ausführlich dokumentierte Datei als um einen kurzen Stub-Auszug."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            comment_lines = "\n".join(f"# Zeile {i} der Dokumentation" for i in range(1, 15))
            (project_dir / "notes.py").write_text(comment_lines + "\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_empty_init_file_not_flagged(self):
        """Ein bewusst leeres `__init__.py` als reiner Package-Marker ist kein Stub."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "__init__.py").write_text("", encoding="utf-8")
            (project_dir / "app.py").write_text(
                "def real_function() -> int:\n    return 42\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)


class TestUndefinedEntrypointNames(unittest.TestCase):
    """Deckt den ecotrack_ai-Fund ab (root-cause-Ticket 2026-09-17): `app/main.py` registrierte
    `app.include_router(fleet_router)` u.a., ohne die Module je zu importieren - garantierter
    `NameError` beim App-Start, den keiner der bisherigen Checks erfasste."""

    def test_flags_router_used_but_never_imported(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app").mkdir()
            (project_dir / "app" / "main.py").write_text(
                "from fastapi import FastAPI\n\n"
                "app = FastAPI()\n"
                "app.include_router(fleet_router)\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            undefined = [i for i in report.issues if i.kind == "undefined_entrypoint_name"]
            self.assertEqual(len(undefined), 1)
            self.assertEqual(undefined[0].file_path, "app/main.py")
            self.assertIn("fleet_router", undefined[0].message)

    def test_router_imported_before_use_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app").mkdir()
            (project_dir / "app" / "api").mkdir()
            (project_dir / "app" / "__init__.py").write_text("", encoding="utf-8")
            (project_dir / "app" / "api" / "__init__.py").write_text("", encoding="utf-8")
            (project_dir / "app" / "api" / "fleet.py").write_text(
                "from fastapi import APIRouter\n\nfleet_router = APIRouter()\n",
                encoding="utf-8",
            )
            (project_dir / "app" / "main.py").write_text(
                "from fastapi import FastAPI\n"
                "from app.api.fleet import fleet_router\n\n"
                "app = FastAPI()\n"
                "app.include_router(fleet_router)\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            undefined = [i for i in report.issues if i.kind == "undefined_entrypoint_name"]
            self.assertEqual(undefined, [])

    def test_name_used_only_inside_function_body_not_flagged(self):
        """Modul-Ebene beschränkt: eine Variable, die erst innerhalb einer Funktion verwendet und
        dort per Parameter/Closure gebunden wird, ist keine Modul-Ebenen-NameError-Quelle."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.py").write_text(
                "def handler(fleet_router):\n    return fleet_router\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            undefined = [i for i in report.issues if i.kind == "undefined_entrypoint_name"]
            self.assertEqual(undefined, [])

    def test_non_entrypoint_file_not_scanned(self):
        """Nur main.py/app.py werden geprüft - andere Dateien mit demselben Muster nicht (siehe
        _ENTRYPOINT_FILENAMES-Docstring: Scoping in Nicht-Einstiegsdateien ist fehleranfälliger)."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "routes.py").write_text(
                "register(fleet_router)\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            undefined = [i for i in report.issues if i.kind == "undefined_entrypoint_name"]
            self.assertEqual(undefined, [])

    def test_wildcard_import_disables_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                "from app.routers import *\n\ninclude_all(fleet_router)\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            undefined = [i for i in report.issues if i.kind == "undefined_entrypoint_name"]
            self.assertEqual(undefined, [])


class TestTestRequestsUndeclaredRoutes(unittest.TestCase):
    """Deckt den docu_guard-Fund ab (2026-09-17): eine Testsuite rief `POST /api/v1/documents`
    auf, der tatsächliche Endpunkt lautete `POST /upload` - eine frei erfundene statt aus dem
    Backend-Code gelesene Route."""

    def test_flags_test_calling_nonexistent_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app").mkdir()
            (project_dir / "app" / "main.py").write_text(
                "from fastapi import FastAPI\n\n"
                "app = FastAPI()\n\n"
                "@app.post('/upload', status_code=201)\n"
                "def upload_document():\n"
                "    return {'id': 1}\n",
                encoding="utf-8",
            )
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_api.py").write_text(
                "def test_create_document(client):\n"
                "    response = client.post('/api/v1/documents', json={'title': 'x'})\n"
                "    assert response.status_code == 200\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            mismatches = [i for i in report.issues if i.kind == "test_route_mismatch"]
            self.assertEqual(len(mismatches), 1)
            self.assertEqual(mismatches[0].file_path, "tests/test_api.py")
            self.assertIn("/api/v1/documents", mismatches[0].message)

    def test_matching_route_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app").mkdir()
            (project_dir / "app" / "main.py").write_text(
                "from fastapi import FastAPI\n\n"
                "app = FastAPI()\n\n"
                "@app.post('/upload', status_code=201)\n"
                "def upload_document():\n"
                "    return {'id': 1}\n",
                encoding="utf-8",
            )
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_api.py").write_text(
                "def test_upload(client):\n"
                "    response = client.post('/upload', json={'title': 'x'})\n"
                "    assert response.status_code == 201\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            mismatches = [i for i in report.issues if i.kind == "test_route_mismatch"]
            self.assertEqual(mismatches, [])

    def test_router_prefix_and_path_param_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app").mkdir()
            (project_dir / "app" / "main.py").write_text(
                "from fastapi import FastAPI\n"
                "from app.routers import pipelines\n\n"
                "app = FastAPI()\n"
                "app.include_router(pipelines.router, prefix='/api/v1')\n",
                encoding="utf-8",
            )
            (project_dir / "app" / "routers").mkdir()
            (project_dir / "app" / "routers" / "pipelines.py").write_text(
                "from fastapi import APIRouter\n\n"
                "router = APIRouter()\n\n"
                "@router.get('/pipelines/{pipeline_id}')\n"
                "def get_pipeline(pipeline_id: int):\n"
                "    return {'id': pipeline_id}\n",
                encoding="utf-8",
            )
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_api.py").write_text(
                "def test_get_pipeline(client):\n"
                "    response = client.get('/api/v1/pipelines/42')\n"
                "    assert response.status_code == 200\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            mismatches = [i for i in report.issues if i.kind == "test_route_mismatch"]
            self.assertEqual(mismatches, [])

    def test_dynamic_fstring_path_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.py").write_text(
                "from fastapi import FastAPI\n\napp = FastAPI()\n\n"
                "@app.get('/items/{item_id}')\n"
                "def get_item(item_id: int):\n    return {'id': item_id}\n",
                encoding="utf-8",
            )
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_api.py").write_text(
                "def test_get_item(client):\n"
                "    item_id = 1\n"
                "    response = client.get(f'/items/{item_id}/extra')\n"
                "    assert response.status_code == 200\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            mismatches = [i for i in report.issues if i.kind == "test_route_mismatch"]
            self.assertEqual(mismatches, [])

    def test_non_client_call_not_flagged(self):
        """`session.post(...)` (verbreitet für ausgehende Drittanbieter-HTTP-Mocks) wird bewusst
        nicht geprüft - der Objektname endet nicht auf "client"."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.py").write_text(
                "from fastapi import FastAPI\n\napp = FastAPI()\n\n"
                "@app.get('/health')\ndef health():\n    return {'ok': True}\n",
                encoding="utf-8",
            )
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_webhook.py").write_text(
                "def test_forwards_to_upstream(session):\n"
                "    session.post('/completely/unrelated/upstream/path', json={})\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            mismatches = [i for i in report.issues if i.kind == "test_route_mismatch"]
            self.assertEqual(mismatches, [])

    def test_flags_router_never_included_as_dead_code(self):
        """Realer Fund (hyperion_metrics, 2026-09-17): `app/api/ingestion.py` deklarierte einen
        eigenen `router = APIRouter()`, `app/main.py` registrierte aber nur eigene, inline
        definierte Handler und inkludierte den Router aus `ingestion.py` nie - die Endpunkte des
        Routers sind toter Code."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app").mkdir()
            (project_dir / "app" / "main.py").write_text(
                "from fastapi import FastAPI\n\n"
                "app = FastAPI()\n\n"
                "@app.post('/api/v1/metrics', status_code=202)\n"
                "def ingest_metric():\n"
                "    return {'status': 'accepted'}\n",
                encoding="utf-8",
            )
            (project_dir / "app" / "api").mkdir()
            (project_dir / "app" / "api" / "ingestion.py").write_text(
                "from fastapi import APIRouter\n\n"
                "router = APIRouter()\n\n"
                "@router.post('/metrics', status_code=202)\n"
                "def ingest_metric():\n"
                "    return {'status': 'accepted'}\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            unwired = [i for i in report.issues if i.kind == "unwired_api_router"]
            self.assertEqual(len(unwired), 1)
            self.assertIn("app/api/ingestion.py", unwired[0].file_path)

    def test_flags_test_against_dead_router_endpoint_as_mismatch(self):
        """Erweiterung desselben Funds: ein Test, der gegen den toten Router-Pfad `/metrics`
        aufruft (statt gegen den real bedienten `/api/v1/metrics`), muss als `test_route_mismatch`
        auffallen - vorher wurde er fälschlich als "deklariert" durchgewunken."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app").mkdir()
            (project_dir / "app" / "main.py").write_text(
                "from fastapi import FastAPI\n\n"
                "app = FastAPI()\n\n"
                "@app.post('/api/v1/metrics', status_code=202)\n"
                "def ingest_metric():\n"
                "    return {'status': 'accepted'}\n",
                encoding="utf-8",
            )
            (project_dir / "app" / "api").mkdir()
            (project_dir / "app" / "api" / "ingestion.py").write_text(
                "from fastapi import APIRouter\n\n"
                "router = APIRouter()\n\n"
                "@router.post('/metrics', status_code=202)\n"
                "def ingest_metric():\n"
                "    return {'status': 'accepted'}\n",
                encoding="utf-8",
            )
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_metrics.py").write_text(
                "def test_ingest(client):\n"
                "    response = client.post('/metrics', json={'name': 'cpu'})\n"
                "    assert response.status_code == 202\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            mismatches = [i for i in report.issues if i.kind == "test_route_mismatch"]
            self.assertEqual(len(mismatches), 1)
            self.assertIn("/metrics", mismatches[0].message)

    def test_included_router_via_bare_import_not_flagged(self):
        """Zweite verbreitete FastAPI-Konvention (`from ... import router; include_router(
        router)` statt `include_router(modul.router)`) darf keinen Fehlalarm auslösen."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app").mkdir()
            (project_dir / "app" / "main.py").write_text(
                "from fastapi import FastAPI\n"
                "from app.api.ingestion import router\n\n"
                "app = FastAPI()\n"
                "app.include_router(router)\n",
                encoding="utf-8",
            )
            (project_dir / "app" / "api").mkdir()
            (project_dir / "app" / "api" / "ingestion.py").write_text(
                "from fastapi import APIRouter\n\n"
                "router = APIRouter()\n\n"
                "@router.post('/metrics', status_code=202)\n"
                "def ingest_metric():\n"
                "    return {'status': 'accepted'}\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            unwired = [i for i in report.issues if i.kind == "unwired_api_router"]
            self.assertEqual(unwired, [])


class TestAuditClaimedFixes(unittest.TestCase):
    """Deckt den EventForge-Fund ab (KI-Team-Analyse 20260916_154524):
    `docs/SECURITY_AUDIT.md` markierte SEC-01 als "Behoben" und verwies auf
    `app/core/security.py`/`validate_relay_url()` - diese Datei existierte nie."""

    def test_flags_table_row_referencing_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.py").write_text("def real_function(): pass\n", encoding="utf-8")
            (project_dir / "docs").mkdir()
            (project_dir / "docs" / "SECURITY_AUDIT.md").write_text(
                "| ID | Befund | Komponente | Schweregrad | Status |\n"
                "|---|---|---|---|---|\n"
                "| SEC-01 | SSRF via Forwarding-URL | `app/core/security.py`, `app/main.py` | Kritisch | Behoben |\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            missing = [i for i in report.issues if i.file_path == "app/core/security.py"]
            self.assertEqual(len(missing), 1)
            self.assertIn("existiert im Projekt nicht", missing[0].message)

    def test_flags_implementation_line_referencing_missing_symbol(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app").mkdir()
            (project_dir / "app" / "core").mkdir()
            (project_dir / "app" / "core" / "security.py").write_text(
                "def other_function():\n    pass\n", encoding="utf-8",
            )
            (project_dir / "docs").mkdir()
            (project_dir / "docs" / "SECURITY_AUDIT.md").write_text(
                "- **Implementierung:** `validate_relay_url()` in `app/core/security.py`.\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            hit = [i for i in report.issues if "validate_relay_url" in i.message]
            self.assertEqual(len(hit), 1)
            self.assertIn("nicht definiert", hit[0].message)

    def test_does_not_flag_when_symbol_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app").mkdir()
            (project_dir / "app" / "core").mkdir()
            (project_dir / "app" / "core" / "security.py").write_text(
                "def validate_relay_url(url: str) -> bool:\n    return True\n", encoding="utf-8",
            )
            (project_dir / "docs").mkdir()
            (project_dir / "docs" / "SECURITY_AUDIT.md").write_text(
                "- **Implementierung:** `validate_relay_url()` in `app/core/security.py`.\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            hit = [i for i in report.issues if "validate_relay_url" in i.message]
            self.assertEqual(hit, [])

    def test_does_not_flag_non_audit_docs(self):
        """Ein normales README/ADR, das dieselben Muster enthält, aber nicht "audit" heißt,
        wird bewusst NICHT geprüft (Architektur-/Planungsdokumente beschreiben oft Zukünftiges)."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.py").write_text("def real_function(): pass\n", encoding="utf-8")
            (project_dir / "README.md").write_text(
                "| SEC-01 | SSRF | `app/core/security.py` | Kritisch | Behoben |\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertEqual(
                [i for i in report.issues if i.file_path == "app/core/security.py"], [],
            )


if __name__ == "__main__":
    unittest.main()
