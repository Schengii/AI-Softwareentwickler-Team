// In der Anomalien-Sektion:
<section className="bg-gray-800 p-6 rounded-lg border border-gray-700" aria-live="polite">
  <h2 className="text-xl font-semibold mb-4">Aktuelle Anomalien</h2>
  {anomalies.length === 0 ? (
    <p className="text-gray-500">Keine Anomalien gefunden.</p>
  ) : (
    <ul className="space-y-2">
      {anomalies.map((a) => (
        <li key={a.id} className="p-3 bg-gray-900 rounded border-l-4 border-[#6366F1]">
          <span className="font-bold uppercase text-xs" aria-label={`Schweregrad: ${a.severity}`}>
            [{a.severity}]
          </span> {a.description}
        </li>
      ))}
    </ul>
  )}
</section>
