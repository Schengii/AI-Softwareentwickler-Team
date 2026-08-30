import os

# Konfiguration für die Datenbankwahl
USE_SQLITE = os.getenv("USE_SQLITE", "True") == "True"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./kanban.db")
