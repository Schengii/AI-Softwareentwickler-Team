# In-Process ML-Engine mit Standard-Library Fallback für Flotten-Emissionen

Status: Angenommen

## Kontext

Fleet-Prognosen für Emissionen und Energieverbräuche erfordern ML-Modelle. Zur Wahl standen externer ML-Server (Triton/TorchServe) vs. In-Process Scikit-Learn/NumPy mit Standard-Library Fallback.

## Entscheidung

In-Process ML-Engine mit Scikit-learn/NumPy und robustem Standard-Library (math/statistics) Fallback. Keine Abhängigkeit von externen Model-Servern.

## Konsequenzen

Vorteile: ML-Vorhersagen (CO2-Ausstoß, Verbrauch, Elektrifizierungs-ROI) funktionieren deterministisch und ohne Ausfall, selbst in Minimalumgebungen ohne compilierte Wheels. Nachteile: Begrenzte Modellkomplexität (Linear/Gradient Regression und Heuristiken), aber optimal für Flotten-Telemetrie.
