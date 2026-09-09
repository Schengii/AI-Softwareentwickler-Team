import React from 'react';
import AgentStatusBadge from './components/AgentStatusBadge';

const App: React.FC = () => {
  return (
    <div className="min-h-screen bg-gray-100 p-8">
      <header className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">DevOps Agent Dashboard</h1>
      </header>
      <main>
        <div className="bg-white p-6 rounded-lg shadow">
          <h2 className="text-lg font-semibold mb-4">System Status</h2>
          <AgentStatusBadge status="idle" />
        </div>
      </main>
    </div>
  );
};

export default App;
