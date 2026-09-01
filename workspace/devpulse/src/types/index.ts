export type HealthStatus = 'healthy' | 'degraded' | 'critical' | 'unknown';
export type IncidentSeverity = 'low' | 'medium' | 'high' | 'critical';
export type IncidentStatus = 'open' | 'investigating' | 'identified' | 'monitoring' | 'resolved';

export interface ServiceMetric {
  timestamp: string;
  responseTimeMs: number;
  successRate: number;
  cpuUsage: number;
  memoryUsage: number;
}

export interface MicroService {
  id: string;
  name: string;
  category: string;
  endpoint: string;
  status: HealthStatus;
  latencyMs: number;
  uptimePercentage: number;
  lastChecked: string;
  metricsHistory: ServiceMetric[];
}

export interface Incident {
  id: string;
  serviceId: string;
  serviceName: string;
  title: string;
  description: string;
  severity: IncidentSeverity;
  status: IncidentStatus;
  assignee?: string;
  createdAt: string;
  updatedAt: string;
  resolvedAt?: string;
}

export interface WSMessage {
  type: 'service_update' | 'incident_new' | 'incident_update';
  payload: MicroService | Incident;
}
