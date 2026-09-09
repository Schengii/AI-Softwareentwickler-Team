import React, { useEffect, useState } from 'react';
import AgentStatusBadge from './AgentStatusBadge';

interface Agent {
  id: string;
  name: string;
  status: 'active' | 'idle' | 'error';
  last_heartbeat: string;
}

const Dashboard: React.FC = () => {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // REST Fetch für initialen Status
    const fetchStatus = async () => {
      try {
        const response = await fetch('/api/v1/dashboard/status');
        if (!response.ok) throw new Error('Fehler beim Laden des Status');
        const data = await response.json();
        setAgents(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
      }
    };

    fetchStatus();

    // WebSocket für Echtzeit-Updates
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${protocol}://${window.location.host}/api/v1/ws/agents`);

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      // Annahme: Nachricht enthält aktualisierte Agentenliste oder spezifisches Update
      if (message.type === 'agent_update') {
        setAgents((prev) => 
          prev.map((a) => a.id === message.data.id ? { ...a, ...message.data } : a)
        );
      }
    };

    return () => ws.close();
  }, []);

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-gray-800">Agenten-Monitoring</h2>
      {error && <div className="p-4 bg-red-100 text-red-700 rounded">{error}</div>}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {agents.map((agent) => (
          <div key={agent.id} className="p-4 bg-white rounded shadow border border-gray-200">
            <div className="flex justify-between items-center">
              <span className="font-medium">{agent.name}</span>
              <AgentStatusBadge status={agent.status} />
            </div>
            <p className="text-sm text-gray-500 mt-2">
              Letztes Update: {new Date(agent.last_heartbeat).toLocaleTimeString()}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
};

export default Dashboard;
