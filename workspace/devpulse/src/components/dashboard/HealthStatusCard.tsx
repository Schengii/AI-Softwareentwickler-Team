import React from 'react';
import { MicroService } from '../../types';
import { CheckCircle2, AlertTriangle, XCircle, Clock } from 'lucide-react';

interface Props {
  services: MicroService[];
}

export const HealthStatusCard: React.FC<Props> = ({ services }) => {
  const healthyCount = services.filter((s) => s.status === 'healthy').length;
  const degradedCount = services.filter((s) => s.status === 'degraded').length;
  const criticalCount = services.filter((s) => s.status === 'critical').length;
  
  const avgLatency = Math.round(
    services.reduce((acc, curr) => acc + curr.latencyMs, 0) / (services.length || 1)
  );

  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
      <div className="bg-white dark:bg-slate-800 p-4 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-500 dark:text-slate-400">Operational Services</p>
          <h3 className="text-2xl font-bold text-slate-900 dark:text-white mt-1">{healthyCount} / {services.length}</h3>
        </div>
        <div className="p-3 bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 rounded-lg">
          <CheckCircle2 className="w-6 h-6" />
        </div>
      </div>

      <div className="bg-white dark:bg-slate-800 p-4 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-500 dark:text-slate-400">Degraded Services</p>
          <h3 className="text-2xl font-bold text-amber-600 dark:text-amber-400 mt-1">{degradedCount}</h3>
        </div>
        <div className="p-3 bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400 rounded-lg">
          <AlertTriangle className="w-6 h-6" />
        </div>
      </div>

      <div className="bg-white dark:bg-slate-800 p-4 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-500 dark:text-slate-400">Critical Incidents</p>
          <h3 className="text-2xl font-bold text-rose-600 dark:text-rose-400 mt-1">{criticalCount}</h3>
        </div>
        <div className="p-3 bg-rose-100 dark:bg-rose-900/30 text-rose-600 dark:text-rose-400 rounded-lg">
          <XCircle className="w-6 h-6" />
        </div>
      </div>

      <div className="bg-white dark:bg-slate-800 p-4 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-500 dark:text-slate-400">Avg Response Time</p>
          <h3 className="text-2xl font-bold text-slate-900 dark:text-white mt-1">{avgLatency} ms</h3>
        </div>
        <div className="p-3 bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 rounded-lg">
          <Clock className="w-6 h-6" />
        </div>
      </div>
    </div>
  );
};
