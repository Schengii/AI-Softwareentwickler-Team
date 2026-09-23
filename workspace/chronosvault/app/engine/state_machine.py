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
        if not payload:
            return False
        
        # simple evaluation for "key == val" or "key != val"
        # and also variable comparison like "actor != submitter"
        if "!=" in guard:
            left, right = [x.strip() for x in guard.split("!=")]
            left_val = payload.get(left, left)
            right_val = payload.get(right, right)
            return str(left_val) != str(right_val)
        elif "==" in guard:
            left, right = [x.strip() for x in guard.split("==")]
            left_val = payload.get(left, left)
            right_val = payload.get(right, right)
            return str(left_val) == str(right_val)
            
        return True
