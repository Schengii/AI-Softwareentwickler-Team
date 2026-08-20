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
    
    @classmethod
    def get_operation(cls, symbol):
        return cls._ops.get(symbol)
