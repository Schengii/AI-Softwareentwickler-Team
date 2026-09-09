import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 10 },
    { duration: '1m', target: 50 },
    { duration: '30s', target: 100 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'], // 95% der Requests unter 500ms
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000';

export default function () {
  const url = `${BASE_URL}/api/v1/audit/run`;
  const payload = JSON.stringify({
    repo_url: 'https://github.com/test/repo',
    scan_type: 'sast'
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
    },
  };

  const res = http.post(url, payload, params);

  check(res, {
    'status is 200 or 202': (r) => r.status === 200 || r.status === 202,
  });

  sleep(1);
}
