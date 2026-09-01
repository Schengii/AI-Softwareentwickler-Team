import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { HealthStatusCard } from './components/dashboard/HealthStatusCard';
import { DevPulseWebSocket } from './services/websocket';
import { MicroService, WSMessage } from './types';

const App: React.FC = () => {
  const [services, setServices] = useState<MicroService[]>([]);

  // Initialer Ladevorgang über die REST-API (/api/v1/services), danach hält die WebSocket-
  // Verbindung den Zustand live aktuell - vermeidet, dass die Karte beim ersten Laden leer
  // bleibt, bis das erste WS-Event eintrifft.
  useEffect(() => {
    axios
      .get<{ services: MicroService[] }>('/api/v1/services')
      .then((res) => setServices(res.data.services))
      .catch((err) => console.error('[DevPulse] Konnte Services nicht laden:', err));
  }, []);

  useEffect(() => {
    const socket = new DevPulseWebSocket();
    const unsubscribe = socket.subscribe((message: WSMessage) => {
      if (message.type === 'service_update') {
        const updated = message.payload as MicroService;
        setServices((prev) => {
          const exists = prev.some((s) => s.id === updated.id);
          return exists
            ? prev.map((s) => (s.id === updated.id ? updated : s))
            : [...prev, updated];
        });
      }
    });
    socket.connect();

    return () => {
      unsubscribe();
      socket.disconnect();
    };
  }, []);

  return (
    <div className="min-h-screen p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">DevPulse</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Live-Übersicht über Microservice-Gesundheit &amp; Incidents
        </p>
      </header>
      <HealthStatusCard services={services} />
    </div>
  );
};

export default App;
