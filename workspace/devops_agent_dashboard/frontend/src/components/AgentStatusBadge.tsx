import React from 'react';

interface Props {
  status: 'idle' | 'running' | 'error';
}

export const AgentStatusBadge: React.FC<Props> = ({ status }) => {
  const statusLabels = {
    idle: 'Agent ist bereit',
    running: 'Agent führt Aufgabe aus',
    error: 'Agent hat einen Fehler gemeldet'
  };

  return (
    <span 
      className={`badge badge-${status}`} 
      role="status" 
      aria-label={statusLabels[status]}
    >
      {status}
    </span>
  );
};

export default AgentStatusBadge;
