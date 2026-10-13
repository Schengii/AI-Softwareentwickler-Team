"""TEMPORAER (Diagnose, wird wieder geloescht): gibt pytest-Interna als GitHub-Annotation aus."""
import sys


def _emit(title, text):
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::error title={title}::{text[:3500]}", file=sys.stderr, flush=True)


def pytest_internalerror(excrepr, excinfo):
    _emit("pytest-internalerror", str(excrepr))


def pytest_load_initial_conftests(early_config, parser, args):
    import pytest
    _emit("pytest-version", f"pytest {pytest.__version__}; python {sys.version.split()[0]}")
