import os
import sys

# Sicherstellen, dass das Projektverzeichnis im Pfad ist
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    import fastapi
    print(f"FastAPI found: {fastapi.__version__}")
except ImportError:
    print("FastAPI NOT found")
