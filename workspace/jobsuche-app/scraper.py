import sqlite3
import os
from datetime import datetime

DB_FILE = "jobs_tracker.db"
UPLOAD_DIR = "uploads"

def init_db():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Tabelle: Bewerbungen
    c.execute('''CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company TEXT NOT NULL,
        position TEXT NOT NULL,
        location TEXT,
        apply_date TEXT,
        channel TEXT,
        status TEXT DEFAULT 'Ausstehend',
        notes TEXT,
        job_url TEXT
    )''')
    
    # Tabelle: Gescrapte / Gefundene Jobs
    c.execute('''CREATE TABLE IF NOT EXISTS scraped_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        portal TEXT,
        title TEXT,
        company TEXT,
        location TEXT,
        url TEXT UNIQUE,
        match_score INTEGER,
        found_date TEXT
    )''')

    # Tabelle: Einstellungen
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')

    # Tabelle: Dokumente
    c.execute('''CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_type TEXT,
        file_name TEXT,
        file_path TEXT,
        upload_date TEXT
    )''')

    conn.commit()
    conn.close()

def get_connection():
    return sqlite3.connect(DB_FILE)

# CRUD Bewerbungen
def add_application(company, position, location, apply_date, channel, status, notes, job_url=""):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''INSERT INTO applications (company, position, location, apply_date, channel, status, notes, job_url)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', 
              (company, position, location, apply_date, channel, status, notes, job_url))
    conn.commit()
    conn.close()

def get_applications():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM applications ORDER BY apply_date DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def update_application_status(app_id, new_status, notes):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE applications SET status = ?, notes = ? WHERE id = ?", (new_status, notes, app_id))
    conn.commit()
    conn.close()

def delete_application(app_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM applications WHERE id = ?", (app_id,))
    conn.commit()
    conn.close()

# CRUD Einstellungen
def save_setting(key, value):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_setting(key, default=""):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default

# CRUD Dokumente
def save_document_info(doc_type, file_name, file_path):
    conn = get_connection()
    c = conn.cursor()
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    c.execute("INSERT INTO documents (doc_type, file_name, file_path, upload_date) VALUES (?, ?, ?, ?)",
              (doc_type, file_name, file_path, date_str))
    conn.commit()
    conn.close()

def get_documents():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, doc_type, file_name, file_path, upload_date FROM documents ORDER BY upload_date DESC")
    rows = c.fetchall()
    conn.close()
    return rows
