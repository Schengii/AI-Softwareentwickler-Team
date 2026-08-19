import pytest
from calculator import add

def test_add_positive():
    assert add(2, 3) == 5

def test_add_negative():
    assert add(-1, -1) == -2

def test_add_mixed():
    assert add(-1, 1) == 0
