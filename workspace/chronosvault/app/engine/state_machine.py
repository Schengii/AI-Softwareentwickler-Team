from typing import Dict, Any, List, Optional
from app.db.models import WorkflowDefinition

class StateMachineError(Exception):
    pass

class StateMachineEngine:
    @staticmethod
    def validate_transition(definition: WorkflowDefinition, current_state: str, action: str, payload: Optional[Dict[str, Any]] = None) -> str:
        transitions = definition.transitions
        for t in transitions:
            if t.get("from") == current_state and t.get("action") == action:
                # Evaluate guards if any
                guards = t.get("guards", [])
                for guard in guards:
                    if not StateMachineEngine._evaluate_guard(guard, payload):
                        raise StateMachineError(f"Guard '{guard}' failed for action '{action}'")
                return t.get("to")
        raise StateMachineError(f"Invalid transition from '{current_state}' with action '{action}'")

    @staticmethod
    def _evaluate_guard(guard: str, payload: Optional[Dict[str, Any]]) -> bool:
        # Simple guard evaluation logic for demonstration
        if not payload:
            return False
        # e.g. "role == admin"
        if "==" in guard:
            key, val = [x.strip() for x in guard.split("==")]
            return str(payload.get(key, "")) == val
        return True
