import streamlit as st
import pandas as pd
import os
from datetime import datetime

import database as db
import scraper

# DB initialisieren
db.init_db()

st.set_page_config(page_title="JobTracker & Matcher", page_icon="💼", layout="wide")

st.title("💼 Job-Finder & Bewerbungsmanager")
st.caption("Speziell optimiert für Fachinformatiker für Anwendungsentwicklung")

# Tabs Navigation
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Dashboard", 
    "🔍 Job-Suche & Crawler", 
    "📋 Bewerbungs-Tracker", 
    "📁 Dokumentenablage", 
    "⚙️ Einstellungen"
])

# --- TAB 1: DASHBOARD ---
with tab1:
    st.header("Überblick & Statistik")
    
    apps = db.get_applications()
    df_apps = pd.DataFrame(apps, columns=["ID", "Firma", "Position", "Standort", "Datum", "Kanal", "Status", "Notizen", "URL"])
    
    col1, col2, col3, col4 = st.columns(4)
    total_apps = len(df_apps)
    pending_apps = len(df_apps[df_apps['Status'] == 'Ausstehend']) if not df_apps.empty else 0
    interview_apps = len(df_apps[df_apps['Status'] == 'Rückmeldung / Gespräch']) if not df_apps.empty else 0
    rejected_apps = len(df_apps[df_apps['Status'] == 'Abgelehnt']) if not df_apps.empty else 0
    
    col1.metric("Gesamt Bewerbungen", total_apps)
    col2.metric("Ausstehend", pending_apps)
    col3.metric("Rückmeldung / Gespräch", interview_apps)
    col4.metric("Absagen", rejected_apps)
    
    st.divider()
    
    if not df_apps.empty:
        st.subheader("Aktuelle Bewerbungen")
        st.dataframe(
            df_apps[["Firma", "Position", "Datum", "Kanal", "Status", "Notizen"]],
            use_container_width=True
        )
    else:
        st.info("Noch keine Bewerbungen erfasst. Nutze den Tab 'Bewerbungs-Tracker', um deine erste Bewerbung anzulegen.")

# --- TAB 2: JOB-SUCHE & CRAWLER ---
with tab2:
    st.header("Stellensuche & Portal-Crawler")
    
    keywords = db.get_setting("keywords", "Fachinformatiker, Python, SQL, REST API")
    location = db.get_setting("location", "Deutschland / Remote")
    
    st.write(f"**Aktuelle Suchkriterien:** `{keywords}` in `{location}`")
    
    if st.button("🚀 Crawler jetzt starten (Stepstone, getInIT, Indeed)", type="primary"):
        with st.spinner("Durchsuche Jobportale nach passenden Stellenangeboten..."):
            scraper.search_jobs(keywords, location)
            st.success("Suche abgeschlossen!")
            
    st.divider()
    st.subheader("Gefundene Stellenangebote")
    
    scraped = scraper.get_saved_scraped_jobs()
    if scraped:
        df_scraped = pd.DataFrame(scraped, columns=["Portal", "Titel", "Firma", "Standort", "Link", "Match %", "Gefunden am"])
        st.dataframe(df_scraped, use_container_width=True)
    else:
        st.info("Noch keine Jobs gecrawlt. Klicke auf 'Crawler jetzt starten'.")

# --- TAB 3: BEWERBUNGS-TRACKER ---
with tab3:
    st.header("Bewerbung erfassen & verwalten")
    with st.form("new_app_form"):
        col_f1, col_f2 = st.columns(2)
        company = col_f1.text_input("Unternehmen *")
        position = col_f2.text_input("Job-Bezeichnung / Rolle *")
        location_app = col_f1.text_input("Standort")
        channel = col_f2.selectbox("Bewerbungskanal", ["E-Mail", "Portal / Karriere-Website", "LinkedIn", "getInIT", "StepStone", "Indeed", "Sonstiges"])
        apply_date = col_f1.date_input("Bewerbungsdatum", datetime.now()).strftime("%Y-%m-%d")
        status = col_f2.selectbox("Status", ["Ausstehend", "Rückmeldung / Gespräch", "Angebot erhalten", "Abgelehnt"])
        job_url = st.text_input("Link zum Stellenangebot")
        notes = st.text_area("Notizen / Ansprechpartner")
        
        submitted = st.form_submit_button("💾 Bewerbung speichern")
        if submitted and company and position:
            db.add_application(company, position, location_app, apply_date, channel, status, notes, job_url)
            st.success(f"Bewerbung bei {company} erfolgreich erfasst!")
            st.rerun()

# --- TAB 4: DOKUMENTENABLAGE ---
with tab4:
    st.header("Bewerbungsunterlagen")
    doc_type = st.selectbox("Dokumenten-Typ", ["Lebenslauf", "Anschreiben", "IHK Zeugnis", "Zertifikat", "Arbeitszeugnis", "Sonstiges"])
    uploaded_file = st.file_uploader("Datei hochladen (PDF, DOCX, PNG)", type=["pdf", "docx", "png", "jpg"])
    
    if uploaded_file is not None:
        if st.button("Dokument in Ablage speichern"):
            file_path = os.path.join(db.UPLOAD_DIR, uploaded_file.name)
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            db.save_document_info(doc_type, uploaded_file.name, file_path)
            st.success(f"{uploaded_file.name} erfolgreich als {doc_type} hinterlegt!")
            st.rerun()

    st.divider()
    st.subheader("Hinterlegte Dokumente")
    docs = db.get_documents()
    if docs:
        for doc in docs:
            st.write(f"📄 **{doc[1]}:** `{doc[2]}` *(Hochgeladen am {doc[4]})*")
    else:
        st.info("Noch keine Dokumente hochgeladen.")

# --- TAB 5: EINSTELLUNGEN ---
with tab5:
    st.header("Suchpräferenzen")
    new_kw = st.text_input("Keywords / Fähigkeiten (Komma-getrennt)", db.get_setting("keywords", "Fachinformatiker, Python, SQL, REST API"))
    new_loc = st.text_input("Bevorzugte Standorte / Remote", db.get_setting("location", "Deutschland / Remote"))
    
    if st.button("Einstellungen speichern"):
        db.save_setting("keywords", new_kw)
        db.save_setting("location", new_loc)
        st.success("Einstellungen gespeichert!")
