from datetime import datetime

from app.models import Project, TimeEntry

# Test-Szenarien für Abrechnungslogik
# 1. Berechnung bei validem Projekt mit Stundensatz
# 2. Berechnung bei Projekt ohne Stundensatz (sollte 0 oder Fehler sein)
# 3. Summierung über mehrere TimeEntries
# 4. Edge-Cases: Keine TimeEntries, teilweise abgerechnete Einträge

def calculate_invoice_amount(project: Project, time_entries: list[TimeEntry]) -> float:
    """
    Hilfsfunktion zur Berechnung des Rechnungsbetrags.
    Wird hier simuliert, da die Geschäftslogik in den Routern/Services liegt.
    """
    if project.hourly_rate is None:
        return 0.0
    
    total_hours = 0.0
    for entry in time_entries:
        if entry.start_time and entry.end_time:
            duration = (entry.end_time - entry.start_time).total_seconds() / 3600
            total_hours += duration
            
    return round(total_hours * project.hourly_rate, 2)

def test_calculate_invoice_amount_success():
    project = Project(id=1, name="Test Projekt", hourly_rate=50.0, owner_id=1)
    entries = [
        TimeEntry(start_time=datetime(2026, 1, 1, 9, 0), end_time=datetime(2026, 1, 1, 11, 0)), # 2h
        TimeEntry(start_time=datetime(2026, 1, 2, 9, 0), end_time=datetime(2026, 1, 2, 10, 30)), # 1.5h
    ]
    # Total 3.5h * 50 = 175.0
    assert calculate_invoice_amount(project, entries) == 175.0

def test_calculate_invoice_amount_no_rate():
    project = Project(id=1, name="Test Projekt", hourly_rate=None, owner_id=1)
    entries = [
        TimeEntry(start_time=datetime(2026, 1, 1, 9, 0), end_time=datetime(2026, 1, 1, 11, 0)),
    ]
    assert calculate_invoice_amount(project, entries) == 0.0

def test_calculate_invoice_amount_empty_entries():
    project = Project(id=1, name="Test Projekt", hourly_rate=50.0, owner_id=1)
    assert calculate_invoice_amount(project, []) == 0.0
