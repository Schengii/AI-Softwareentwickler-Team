# Security Audit Report: EcoChef

## 1. Findings

### 1.1 Unsichere Speicherung des API-Keys im LocalStorage (Kritisch)
**Beschreibung:** Der Gemini API-Key wurde bisher nur im RAM gehalten. Bei einer Persistierung im `localStorage` (für UX erforderlich) läge er im Klartext vor. Ein XSS-Angriff oder "Shoulder Surfing" könnte den Key leicht stehlen.
**Risiko:** Kritisch. Kompromittierung des API-Keys führt zu Missbrauch und potenziellen Kosten.
**Lösung:** Da es sich um eine reine Client-App (Cordova/Web) ohne Backend handelt, ist eine echte asymmetrische Verschlüsselung schwer umsetzbar. Als Mitigation wird der Key vor dem Speichern im `localStorage` mit einem statischen Salt versehen und Base64-codiert (`btoa`). Dies verhindert zumindest das einfache Mitlesen durch unbedarfte Nutzer oder simple Scripte. Wurde in `gemini.service.ts` implementiert.

### 1.2 Fehlende Input-Validierung bei externen API-Aufrufen (Hoch)
**Beschreibung:** Die Prompts an die Gemini-API werden durch unvalidierte User-Inputs (Zutaten, Allergene) zusammengebaut. Dies ermöglicht Prompt-Injection.
**Risiko:** Hoch. Angreifer könnten den LLM-Prompt manipulieren, um unerwünschte Ausgaben zu erzeugen.
**Lösung:** Strikte Validierung und Sanitization der Inputs (Zutaten, Allergene) vor dem Senden an die API. 

### 1.3 Fehlendes Rate-Limiting (Mittel)
**Beschreibung:** Clientseitig gibt es keinen Schutz vor zu vielen API-Aufrufen in kurzer Zeit, was zu 429 Errors und API-Kosten führen kann.
**Risiko:** Mittel.
**Lösung:** Implementierung eines clientseitigen Rate-Limiters (Cooldown) für die `generateRecipe` Funktion.

## 2. Security Checkliste
- [x] API-Key wird nicht im Klartext im Code hardcodiert.
- [x] API-Key wird bei Speicherung im LocalStorage obfuskiert (Base64 + Salt).
- [x] Inputs für Gemini-Prompts werden validiert (Sanitization).
- [x] Fehlermeldungen leaken keine sensiblen Daten (API-Key Maskierung).
- [x] Externe API-Aufrufe (OpenFoodFacts, Gemini) nutzen HTTPS.
