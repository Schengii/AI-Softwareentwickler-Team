import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.models import PipelineRun, StepExecution

logger = logging.getLogger("ExecutionEngine")

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class StepExecutor:
    """Führt einzelne Steps (Shell, HTTP-Ping, Daten-Transform) aus."""

    @staticmethod
    async def execute(step: dict[str, Any]) -> tuple[bool, str]:
        step_type = step.get("type", "").lower()
        
        if step_type == "shell":
            return await StepExecutor._execute_shell(step)
        elif step_type == "http":
            return await StepExecutor._execute_http(step)
        elif step_type == "transform":
            return await StepExecutor._execute_transform(step)
        else:
            return True, f"[INFO] Unbekannter oder generischer Step-Typ '{step_type}'. Erfolgreich simuliert."

    @staticmethod
    async def _execute_shell(step: dict[str, Any]) -> tuple[bool, str]:
        command = step.get("command", "")
        if not command:
            return False, "[ERROR] Kein Shell-Befehl angegeben."

        try:
            # Asynchroner Shell-Prozess
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            output = ""
            if stdout:
                output += stdout.decode(errors="replace")
            if stderr:
                output += ("\n[STDERR]\n" if output else "") + stderr.decode(errors="replace")

            success = (proc.returncode == 0)
            status_text = f"[EXIT_CODE {proc.returncode}]\n{output.strip()}"
            return success, status_text
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - Fängt System-/Subprocess-Fehler für das Log ab
            return False, f"[ERROR Shell-Ausführung fehlgeschlagen]: {exc!s}"

    @staticmethod
    async def _execute_http(step: dict[str, Any]) -> tuple[bool, str]:
        url = step.get("url", "")
        method = step.get("method", "GET").upper()
        if not url:
            return False, "[ERROR] Keine URL angegeben."

        def do_http_request() -> tuple[bool, str]:
            try:
                req = urllib.request.Request(url, method=method, headers={"User-Agent": "PipelinePilot-Ping/1.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    code = resp.getcode()
                    return (200 <= code < 400), f"HTTP {method} {url} -> Status {code}"
            except urllib.error.HTTPError as exc:
                return False, f"HTTP Error {exc.code}: {exc.reason}"
            except Exception as exc:  # noqa: BLE001 - Fängt Netzwerk/DNS-Fehler sicher ab
                return False, f"HTTP Ping fehlgeschlagen: {exc!s}"

        return await asyncio.to_thread(do_http_request)

    @staticmethod
    async def _execute_transform(step: dict[str, Any]) -> tuple[bool, str]:
        op = step.get("transform_op", "json_parse")
        input_data = step.get("input_data", "")

        try:
            if op == "json_parse":
                if isinstance(input_data, str):
                    parsed = json.loads(input_data)
                    return True, f"JSON Parsing erfolgreich: {len(parsed) if isinstance(parsed, (list, dict)) else 1} Einträge verarbeitet."
                return True, f"JSON Daten bereits deserialisiert: {type(input_data).__name__}"
            elif op == "uppercase":
                transformed = str(input_data).upper()
                return True, f"Transform Uppercase Ergebnis: {transformed}"
            elif op == "count_items":
                if isinstance(input_data, list):
                    count = len(input_data)
                elif isinstance(input_data, dict):
                    count = len(input_data.keys())
                else:
                    count = len(str(input_data).splitlines())
                return True, f"Transform Item Count: {count}"
            else:
                return True, f"Standard-Transform '{op}' auf Eingabedaten ausgeführt."
        except Exception as exc:  # noqa: BLE001 - Fängt Transformationsfehler ab
            return False, f"Fehler bei Transform-Operation '{op}': {exc!s}"


class ExecutionEngine:
    """Asynchrone In-Process Task Execution Engine."""

    def __init__(self):
        self.active_tasks: dict[int, asyncio.Task[None]] = {}

    async def trigger_run(self, run_id: int, steps: list[dict[str, Any]]) -> None:
        """Startet den Workflow-Run im asyncio Hintergrund."""
        task = asyncio.create_task(self._execute_pipeline_run(run_id, steps))
        self.active_tasks[run_id] = task

    async def cancel_run(self, run_id: int) -> bool:
        """Bricht einen laufenden Run sauber per asyncio.Task.cancel() ab."""
        task = self.active_tasks.get(run_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    async def shutdown(self) -> None:
        """Shutdown-Handler für laufende Hintergrund-Tasks."""
        for run_id, task in list(self.active_tasks.items()):
            if not task.done():
                task.cancel()
        if self.active_tasks:
            await asyncio.gather(*self.active_tasks.values(), return_exceptions=True)
        self.active_tasks.clear()

    async def _execute_pipeline_run(self, run_id: int, steps: list[dict[str, Any]]) -> None:
        """Führt alle Steps sequentiell aus und trackt Status & Logs in der DB."""
        run_start_time = time.monotonic()
        run_start_dt = utcnow()

        async with AsyncSessionLocal() as session:
            stmt = select(PipelineRun).where(PipelineRun.id == run_id)
            res = await session.execute(stmt)
            run = res.scalar_one_or_none()
            if not run:
                return

            run.status = "RUNNING"
            run.started_at = run_start_dt
            await session.commit()

        overall_status = "SUCCESS"
        error_msg: str | None = None

        try:
            # Lade alle Step-Executions
            async with AsyncSessionLocal() as session:
                step_stmt = (
                    select(StepExecution)
                    .where(StepExecution.run_id == run_id)
                    .order_by(StepExecution.order_index)
                )
                res = await session.execute(step_stmt)
                db_steps = list(res.scalars().all())

            for step_exec in db_steps:
                # Prüfe auf Abbruch
                await asyncio.sleep(0.05) # Yield an den Event Loop

                step_id = step_exec.id
                step_data = next((s for s in steps if s.get("id") == step_exec.step_id or s.get("name") == step_exec.name), {})

                # Update Step auf RUNNING
                step_start_monotonic = time.monotonic()
                step_start_dt = utcnow()
                async with AsyncSessionLocal() as session:
                    await session.execute(
                        update(StepExecution)
                        .where(StepExecution.id == step_id)
                        .values(status="RUNNING", started_at=step_start_dt)
                    )
                    await session.commit()

                # Ausführen
                success, log_output = await StepExecutor.execute(step_data)

                step_end_monotonic = time.monotonic()
                step_duration = round(step_end_monotonic - step_start_monotonic, 4)
                step_end_dt = utcnow()

                step_status = "SUCCESS" if success else "FAILED"

                async with AsyncSessionLocal() as session:
                    await session.execute(
                        update(StepExecution)
                        .where(StepExecution.id == step_id)
                        .values(
                            status=step_status,
                            finished_at=step_end_dt,
                            duration_seconds=step_duration,
                            logs=log_output
                        )
                    )
                    await session.commit()

                if not success:
                    overall_status = "FAILED"
                    error_msg = f"Step '{step_exec.name}' fehlgeschlagen."
                    
                    # Nachfolgende Steps als SKIPPED markieren
                    async with AsyncSessionLocal() as session:
                        await session.execute(
                            update(StepExecution)
                            .where(
                                StepExecution.run_id == run_id,
                                StepExecution.order_index > step_exec.order_index,
                                StepExecution.status == "PENDING"
                            )
                            .values(status="SKIPPED", logs="Übersprungen aufgrund vorherigem Fehler.")
                        )
                        await session.commit()
                    break

        except asyncio.CancelledError:
            overall_status = "CANCELLED"
            error_msg = "Ausführung durch Benutzer abgebrochen."
            # Alle aktuell laufenden / verbliebenen Steps als CANCELLED markieren
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(StepExecution)
                    .where(StepExecution.run_id == run_id, StepExecution.status.in_(["PENDING", "RUNNING"]))
                    .values(status="CANCELLED", logs="Ausführung abgebrochen.")
                )
                await session.commit()
            raise

        except Exception as exc:
            overall_status = "FAILED"
            error_msg = f"Unerwarteter Fehler in der Engine: {exc!s}"
            logger.exception("Engine failure for run %s", run_id)

        finally:
            run_end_dt = utcnow()
            run_duration = round(time.monotonic() - run_start_time, 4)

            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(PipelineRun)
                    .where(PipelineRun.id == run_id)
                    .values(
                        status=overall_status,
                        finished_at=run_end_dt,
                        duration_seconds=run_duration,
                        error_message=error_msg
                    )
                )
                await session.commit()

            # Task aus Registrierung entfernen
            self.active_tasks.pop(run_id, None)

execution_engine = ExecutionEngine()
