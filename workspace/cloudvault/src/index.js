import React from 'react';
import ReactDOM from 'react-dom/client';
import Dashboard from './components/Dashboard';
import { AuthProvider } from './context/AuthContext';
import './index.css';

const App = () => (
  <AuthProvider>
    <Dashboard />
  </AuthProvider>
);

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
