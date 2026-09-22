from agents.tester_agent import TesterAgent


def test_tester_agent_system_prompt_includes_api_prefix_and_timing_guidance():
    """
    Stellt sicher, dass der Tester-Agent bei 404-Fehlern die Router-Registrierung prüft
    und bei Background-Workern auf Timing-Probleme achtet.
    """
    agent = TesterAgent()
    prompt = agent.system_prompt
    
    # Prüfe auf die spezifischen Anweisungen für API-Prefixes
    assert "Router-Registrierung" in prompt, "Tester-Agent muss angewiesen werden, die Router-Registrierung zu prüfen"
    assert "Prefix" in prompt or "Präfix" in prompt, "Tester-Agent muss auf API-Prefixes achten"
    
    # Prüfe auf die spezifischen Anweisungen für Background-Worker und Timings
    assert "Background-Worker" in prompt or "Background-Workern" in prompt, "Tester-Agent muss auf Background-Worker achten"
    assert "asyncio.sleep" in prompt or "Polling" in prompt, "Tester-Agent muss asynchrone Wartezeiten berücksichtigen"
