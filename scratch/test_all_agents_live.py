"""
scratch/test_all_agents_live.py – Führt jeden einzelnen Agenten live aus und misst Status & Modell
"""

import asyncio
import sys
import io

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from agents.orchestrator import Orchestrator
from core.message_bus import AgentTask


async def main():
    orch = Orchestrator()
    print(f"=== STARTE LIVE-TEST ALLER {len(orch._agents)} AGENTEN ===\n")
    
    passed = 0
    failed = 0
    
    for aid, agent in orch._agents.items():
        task = AgentTask(task_id="live_test", agent_id=aid, description="Bestätige kurz deine Funktionsbereitschaft mit Rolle und Status.", context="")
        try:
            res = await agent.execute(task)
            if res.success:
                print(f"✅ [{aid:18}] | {agent.name[:32]:32} | Modell: {res.model_used or 'default':24} | {res.duration_seconds:.2f}s")
                passed += 1
            else:
                print(f"❌ [{aid:18}] | FEHLER: {res.error}")
                failed += 1
        except Exception as e:
            print(f"❌ [{aid:18}] | EXCEPTION: {e}")
            failed += 1

    print(f"\n=== ERGEBNIS: {passed}/{len(orch._agents)} Agenten erfolgreich ({failed} Fehler) ===")


if __name__ == "__main__":
    asyncio.run(main())
