import os

# Verzeichnisstruktur für das Frontend erstellen
os.makedirs('frontend/src/components', exist_ok=True)

# Basis-Struktur für das React-Dashboard
# Hinweis: Da dies ein neues Projekt ist, erstelle ich die notwendigen Dateien für ein React-Frontend.
# Wir nutzen Tailwind CSS wie in ADR 0003 definiert.

# 1. package.json für das Frontend
package_json = """{
  "name": "logpulse-dashboard",
  "version": "0.1.0",
  "private": true,
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "axios": "^1.6.0"
  },
  "devDependencies": {
    "tailwindcss": "^3.3.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0"
  }
}
"""

# 2. Tailwind Konfiguration
tailwind_config = """/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: '#0f172a',
        secondary: '#1e293b',
        accent: '#38bdf8',
        textPrimary: '#f8fafc',
        textSecondary: '#94a3b8',
      }
    },
  },
  plugins: [],
}
"""

with open('frontend/package.json', 'w') as f: f.write(package_json)
with open('frontend/tailwind.config.js', 'w') as f: f.write(tailwind_config)
