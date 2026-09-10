import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 20 }, // Ramp-up auf 20 VUs
    { duration: '1m', target: 20 },  // Halten
    { duration: '30s', target: 0 },  // Ramp-down
  ],
  thresholds: {
    http_req_duration: ['p(95)<200'], // 95% der Requests unter 200ms
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000';

export default function () {
  const params = {
    headers: {
      'Content-Type': 'application/json',
      // 'Authorization': 'Bearer <token>' // Token-Handling bei Bedarf ergänzen
    },
  };

  // Teste die definierten Endpunkte
  const endpoints = [
    '/api/v1/metrics/summary',
    '/api/v1/anomalies',
    '/api/v1/traces',
  ];

  endpoints.forEach((endpoint) => {
    const res = http.get(`${BASE_URL}${endpoint}`, params);
    check(res, {
      [`status is 200 for ${endpoint}`]: (r) => r.status === 200,
    });
  });

  sleep(1);
}
