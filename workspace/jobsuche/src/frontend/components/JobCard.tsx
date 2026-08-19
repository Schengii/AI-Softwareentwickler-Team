/**
 * Barrierefreie, typisierte Job‑Card.
 * Fokus‑Styling & ARIA‑Attribute entsprechen WCAG 2.2 AA.
 */

import React from "react";

export interface JobCardProps {
  id: number;
  title: string;
  company: string;
  location: string;
  salary?: number;
  logoUrl: string; // bereits vom Parent (Container) geladen → kein Service‑Call im UI
}

/**
 * Utility: format salary (Intl.NumberFormat) – pure function, testable.
 */
const formatSalary = (salary?: number): string =>
  salary ? new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" }).format(salary) : "Verhandlungsbasis";

export const JobCard: React.FC<JobCardProps> = ({
  id,
  title,
  company,
  location,
  salary,
  logoUrl,
}) => {
  return (
    <article
      role="article"
      tabIndex={0}
      className="group p-6 bg-white border border-slate-200 rounded-lg shadow-sm hover:shadow-md focus-visible:ring-2 focus-visible:ring-blue-600 transition-shadow"
      aria-labelledby={`job-title-${id}`}
    >
      {/* Bild – alt‑Text leer, weil dekorativ; ARIA‑Label über title */}
      <img src={logoUrl} alt="" className="w-12 h-12 mb-4" loading="lazy" />

      <h3 id={`job-title-${id}`} className="text-xl font-bold text-slate-900 mb-2">
        {title}
      </h3>

      <p className="text-slate-600 mb-1">{company} • {location}</p>

      <p className="text-slate-800 font-medium">{formatSalary(salary)}</p>

      {/* Fokus‑sichtbare “Mehr lesen” – keyboard‑friendly */}
      <button
        className="mt-3 text-blue-600 underline focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-blue-500"
        aria-label={`Mehr Details zu ${title} bei ${company}`}
      >
        Details anzeigen
      </button>
    </article>
  );
};
