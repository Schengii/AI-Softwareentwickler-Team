from abc import ABC, abstractmethod
import math

class Operation(ABC):
    @abstractmethod
    def execute(self, a, b=None): pass

class Add(Operation):
    def execute(self, a, b): return a + b

class Subtract(Operation):
    def execute(self, a, b): return a - b

class SquareRoot(Operation):
    def execute(self, a, b=None): return math.sqrt(a)

class OperationFactory:
    _ops = {"+": Add(), "-": Subtract(), "sqrt": SquareRoot()}
    BINARY_SYMBOLS = {"+", "-"}  # verlangen zwei Operanden (a, b)
    UNARY_SYMBOLS = {"sqrt"}     # verlangen nur einen Operanden (a)

    @classmethod
    def get_operation(cls, symbol):
        return cls._ops.get(symbol)


class Calculator:
    """Zustandsbehaftete Ablauflogik für einen einfachen Kettenrechner (Zahl, Operator,
    Zahl, Operator, ...) ohne eigene "="-Taste - wie ein klassischer Taschenrechner.

    Bewusst getrennt von calculator_gui.py, damit die eigentliche Rechenlogik ohne ein
    echtes Tk-Fenster unit-testbar ist. Behebt einen realen Fund: die GUI rief bisher
    op.execute(val) mit nur EINEM Argument auf, obwohl Add/Subtract zwei Operanden (a, b)
    verlangen - jeder Klick auf "+" oder "-" stürzte sofort mit TypeError ab.
    """

    def __init__(self):
        self._pending_value: float | None = None
        self._pending_op: str | None = None

    def apply(self, op_symbol: str, current_display: float) -> float:
        """Wendet den gewählten Operator auf den aktuellen Anzeigewert an und gibt den
        neuen Anzeigewert zurück."""
        operation = OperationFactory.get_operation(op_symbol)
        if operation is None:
            raise ValueError(f"Unbekannter Operator: '{op_symbol}'")

        if op_symbol in OperationFactory.UNARY_SYMBOLS:
            # Unär (z.B. sqrt): rechnet direkt auf dem Anzeigewert, ohne eine laufende
            # Kettenberechnung zu beeinflussen.
            return operation.execute(current_display)

        if self._pending_value is None:
            # Erste Zahl + Operator: merken und auf die zweite Zahl warten, bevor
            # tatsächlich gerechnet wird (verhindert genau den ursprünglichen Absturz).
            self._pending_value = current_display
            self._pending_op = op_symbol
            return current_display

        # Zweite Zahl wurde eingegeben (current_display) -> jetzt wirklich berechnen.
        pending_operation = OperationFactory.get_operation(self._pending_op)
        result = pending_operation.execute(self._pending_value, current_display)
        # Ergebnis wird zum neuen ersten Operanden, falls direkt der nächste Operator
        # gedrückt wird (Verkettung, z.B. 5 + 3 + 2 -> 8, dann 10).
        self._pending_value = result
        self._pending_op = op_symbol
        return result

    def reset(self) -> None:
        """Setzt eine laufende Kettenberechnung zurück (z.B. nach einem Fehler/Neustart)."""
        self._pending_value = None
        self._pending_op = None
