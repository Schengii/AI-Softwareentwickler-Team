# src/__init__.py
"""
Public API des Pakets.
Exportiert nur das Core‑Interface, damit Legacy‑Klassen intern bleiben.
"""
from .core.use_cases.create_user import execute as create_user
