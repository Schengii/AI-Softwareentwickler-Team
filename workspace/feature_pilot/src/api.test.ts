// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';
import { isAuthenticated, clearSession } from './api';

describe('API Auth Helper', () => {
  it('handles session lifecycle in localStorage', () => {
    localStorage.setItem('feature_pilot_token', 'test-token-123');
    expect(isAuthenticated()).toBe(true);

    clearSession();
    expect(isAuthenticated()).toBe(false);
  });
});
