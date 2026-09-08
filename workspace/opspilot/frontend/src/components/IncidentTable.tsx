export interface Incident {
  id: number;
  title: string;
  status: string;
  created_at: string;
}

interface IncidentTableProps {
  incidents: Incident[];
}

const STATUS_COLORS: Record<string, string> = {
  open: "#b91c1c",
  acknowledged: "#b45309",
  resolved: "#15803d",
};

function formatTimestamp(isoTimestamp: string): string {
  try {
    return new Date(isoTimestamp).toLocaleString("de-DE");
  } catch {
    return isoTimestamp;
  }
}

function IncidentTable({ incidents }: IncidentTableProps) {
  if (incidents.length === 0) {
    return <p style={{ color: "#555" }}>Keine Incidents vorhanden.</p>;
  }

  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <thead>
        <tr style={{ textAlign: "left", borderBottom: "2px solid #ddd" }}>
          <th style={{ padding: "0.5rem" }}>ID</th>
          <th style={{ padding: "0.5rem" }}>Titel</th>
          <th style={{ padding: "0.5rem" }}>Status</th>
          <th style={{ padding: "0.5rem" }}>Erstellt am</th>
        </tr>
      </thead>
      <tbody>
        {incidents.map((incident) => (
          <tr key={incident.id} style={{ borderBottom: "1px solid #eee" }}>
            <td style={{ padding: "0.5rem" }}>{incident.id}</td>
            <td style={{ padding: "0.5rem" }}>{incident.title}</td>
            <td style={{ padding: "0.5rem" }}>
              <span style={{ color: STATUS_COLORS[incident.status] ?? "#555", fontWeight: 600 }}>
                {incident.status}
              </span>
            </td>
            <td style={{ padding: "0.5rem" }}>{formatTimestamp(incident.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default IncidentTable;
