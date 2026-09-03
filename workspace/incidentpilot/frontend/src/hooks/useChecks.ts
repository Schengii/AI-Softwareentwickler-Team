import { useCallback, useEffect, useState } from 'react';

import { createCheck, getChecks } from '../api/checks';
import type { Check, NewCheck } from '../types';

interface UseChecksResult {
  checks: Check[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  addCheck: (data: NewCheck) => Promise<void>;
}

/**
 * Lädt echte Uptime-Checks vom Backend (GET /checks) und stellt eine addCheck()-Mutation
 * (POST /checks) bereit, die die Liste danach automatisch neu lädt - dieselbe Konvention wie
 * in ADR 0001 dokumentiert ("Custom Hooks für Datenabfrage" statt Fetch-Logik direkt in
 * Komponenten).
 */
export function useChecks(): UseChecksResult {
  const [checks, setChecks] = useState<Check[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getChecks();
      setChecks(response.data);
    } catch {
      setError('Checks konnten nicht geladen werden.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const addCheck = useCallback(
    async (data: NewCheck) => {
      await createCheck(data);
      await refresh();
    },
    [refresh],
  );

  return { checks, loading, error, refresh, addCheck };
}
