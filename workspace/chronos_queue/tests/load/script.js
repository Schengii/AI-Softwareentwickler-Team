import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '10s', target: 20 },  // Ramp-up auf 20 VUs
    { duration: '30s', target: 100 }, // Load-Spitze mit 100 VUs
    { duration: '10s', target: 0 },   // Cool-down
  ],
  thresholds: {
    http_req_duration: ['p(95)<150'], // 95% aller Requests < 150ms
    http_req_failed: ['rate<0.01'],   // Fehlerrate < 1%
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000';

export default function () {
  // 1. Healthcheck
  const resHealth = http.get(`${BASE_URL}/health`);
  check(resHealth, { 'health status is 200': (r) => r.status === 200 });

  // 2. Job Erstellung
  const payload = JSON.stringify({
    name: `k6_task_${Math.floor(Math.random() * 10000)}`,
    payload: { action: 'send_email' },
    type: 'instant',
    priority: 'high',
    max_retries: 3
  });

  const params = { headers: { 'Content-Type': 'application/json' } };
  const resJob = http.post(`${BASE_URL}/api/v1/jobs`, payload, params);
  check(resJob, {
    'job created (200/201)': (r) => r.status === 200 || r.status === 201,
  });

  // 3. Metrics
  const resMetrics = http.get(`${BASE_URL}/api/v1/metrics`);
  check(resMetrics, { 'metrics ok': (r) => r.status === 200 });

  sleep(0.2);
}
