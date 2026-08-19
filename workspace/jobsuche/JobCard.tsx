// src/components/JobCard.tsx
import React from "react";

/**
 * Props für die Job‑Karte.
 * id wird für eindeutige ARIA‑Bezüge verwendet.
 */
export interface JobCardProps {
  id: string;
  title: string;
  company: string;
  location: string;
  salary?: string;
  /** Optionaler Text, darf HTML‑Tags enthalten – wird sicher sanitisiert. */
  description?: string;
}

/**
 * JobCard – barrierefrei, responsiv, XSS‑sicher.
 */
export const JobCard: React.FC<JobCardProps> = ({
  id,
  title,
  company,
  location,
  salary,
  description,
}) => {
  /**
   * Wenn `description` HTML enthält, wird es mit DOMPurify
   * gesäubert, bevor es über `dangerouslySetInnerHTML` gerendert wird.
   * Für reinen Text‑Content ist das nicht nötig – React escaped
   * automatisch.
   */
  const sanitizedDescription = React.useMemo(() => {
    if (!description) return null;
    // Lazy‑load von DOMPurify, um Bundle‑Size zu sparen
    const DOMPurify = require("dompurify");
    return DOMPurify.sanitize(description);
  }, [description]);

  return (
    <article
      className="p-6 bg-white border border-slate-200 rounded-lg shadow-sm hover:shadow-md transition-shadow focus-within:ring-2 focus-within:ring-blue-600"
      aria-labelledby={`job-title-${id}`}
      tabIndex={0} // macht die Karte per Tastatur fokussierbar
    >
      {/* Titel – wichtig für Screen‑Reader */}
      <h3
        id={`job-title-${id}`}
        className="text-xl font-bold text-slate-900 mb-2"
      >
        {title}
      </h3>

      {/* Unternehmen & Ort */}
      <p className="text-slate-600 mb-1">
        <span>{company}</span> • <span>{location}</span>
      </p>

      {/* Gehalt (optional) */}
      {salary && (
        <p className="text-slate-700 font-medium" aria-label={`Gehalt: ${salary}`}>
          {salary}
        </p>
      )}

      {/* Beschreibung – max. 3 Zeilen, line‑clamp für Responsive */}
      {description && (
        <p
          className="mt-2 text-slate-500 line-clamp-3"
          // aria‑hidden, weil die komplette Beschreibung auf Detail‑Seite
          // verfügbar ist; nur ein kurzer Auszug wird gezeigt.
          aria-hidden="true"
          // Wenn HTML erlaubt ist, nutzen wir sanitized HTML.
          {...(sanitizedDescription && {
            dangerouslySetInnerHTML: { __html: sanitizedDescription },
          })}
        >
          {/* Fallback‑Text, falls description reiner Text ist */}
          {!sanitizedDescription && description}
        </p>
      )}

      {/* Link zur Detail‑Seite – klarer Fokus‑Ring */}
      <a
        href={`/jobs/${id}`}
        className="inline-block mt-4 text-blue-600 hover:underline focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
      >
        Mehr erfahren
      </a>
    </article>
  );
};
