import React from 'react';
import ReactDOM from 'react-dom/client';
import FeatureToggle from './components/FeatureToggle';
import './styles/a11y.css';

const App: React.FC = () => {
  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-8">
      <header className="max-w-6xl mx-auto mb-8 border-b border-slate-700 pb-4">
        <h1 className="text-3xl font-bold text-indigo-400">NexusForge Dashboard</h1>
        <p className="text-slate-400 text-sm mt-1">Feature Flag & Canary Management</p>
      </header>
      <main className="max-w-6xl mx-auto">
        <FeatureToggle label="Canary Deployment Flag" checked={true} onChange={() => {}} />
      </main>
    </div>
  );
};

const rootElement = document.getElementById('root');
if (rootElement) {
  ReactDOM.createRoot(rootElement).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}

export default App;
