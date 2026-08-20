import math

import pytest

from calculator_core import Add, Calculator, OperationFactory, SquareRoot, Subtract


def test_add_execute():
    assert Add().execute(2, 3) == 5
    assert Add().execute(-1, 1) == 0


def test_subtract_execute():
    assert Subtract().execute(5, 3) == 2
    assert Subtract().execute(0, 5) == -5


def test_square_root_execute():
    assert SquareRoot().execute(9) == 3
    assert SquareRoot().execute(2) == pytest.approx(math.sqrt(2))


def test_operation_factory_returns_correct_operation():
    assert isinstance(OperationFactory.get_operation("+"), Add)
    assert isinstance(OperationFactory.get_operation("-"), Subtract)
    assert isinstance(OperationFactory.get_operation("sqrt"), SquareRoot)
    assert OperationFactory.get_operation("unknown") is None


def test_calculator_binary_operation_completes_on_second_press():
    """Regressionstest für den realen Absturz: die GUI rief früher op.execute(val) mit
    nur EINEM Argument auf, obwohl Add zwei Operanden verlangt. Calculator.apply() löst
    das über eine echte Kettenberechnung (erste Zahl merken, bei der zweiten rechnen)."""
    calc = Calculator()
    after_first_press = calc.apply("+", 5)
    assert after_first_press == 5  # erste Zahl wird nur gemerkt, noch nicht gerechnet

    result = calc.apply("+", 3)
    assert result == 8  # jetzt wird wirklich gerechnet: 5 + 3


def test_calculator_chains_multiple_operations():
    calc = Calculator()
    calc.apply("+", 5)          # merkt 5, wartet auf zweite Zahl
    assert calc.apply("+", 3) == 8   # 5 + 3 = 8, merkt 8 für die nächste Operation
    assert calc.apply("+", 2) == 10  # 8 + 2 = 10


def test_calculator_subtract_chain():
    calc = Calculator()
    calc.apply("-", 10)
    assert calc.apply("-", 4) == 6


def test_calculator_unary_operation_does_not_need_a_second_press():
    calc = Calculator()
    assert calc.apply("sqrt", 16) == 4


def test_calculator_rejects_unknown_operator():
    calc = Calculator()
    with pytest.raises(ValueError):
        calc.apply("*", 5)


def test_calculator_reset_clears_pending_state():
    calc = Calculator()
    calc.apply("+", 5)
    calc.reset()
    # Nach reset() beginnt eine neue Kettenberechnung - der nächste "+"-Druck merkt
    # wieder nur die erste Zahl, statt (fälschlich) mit der alten pending_value zu rechnen.
    assert calc.apply("+", 1) == 1
