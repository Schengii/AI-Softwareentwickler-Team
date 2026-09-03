import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as checksApi from '../api/checks';
import Dashboard from './Dashboard';

vi.mock('../api/checks');

const mockedGetChecks = vi.mocked(checksApi.getChecks);
const mockedCreateCheck = vi.mocked(checksApi.createCheck);

describe('Dashboard', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('lädt und zeigt vorhandene Checks vom Backend an', async () => {
    mockedGetChecks.mockResolvedValue({
      data: [{ id: 1, url: 'https://example.com', interval_seconds: 60, created_at: '2026-01-01T00:00:00Z', owner_id: 1 }],
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    render(<Dashboard />);

    await waitFor(() => expect(screen.getByText('https://example.com')).toBeInTheDocument());
    expect(mockedGetChecks).toHaveBeenCalledTimes(1);
  });

  it('zeigt einen leeren Zustand, wenn keine Checks existieren', async () => {
    mockedGetChecks.mockResolvedValue({ data: [] } as any); // eslint-disable-line @typescript-eslint/no-explicit-any

    render(<Dashboard />);

    await waitFor(() => expect(screen.getByText(/Noch keine Uptime-Checks/i)).toBeInTheDocument());
  });

  it('legt über das Formular einen neuen Check per echtem API-Aufruf an und lädt die Liste neu', async () => {
    mockedGetChecks.mockResolvedValueOnce({ data: [] } as any); // eslint-disable-line @typescript-eslint/no-explicit-any
    mockedCreateCheck.mockResolvedValue({
      data: { id: 2, url: 'https://new.example.com', interval_seconds: 30, created_at: '2026-01-01T00:00:00Z', owner_id: 1 },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    mockedGetChecks.mockResolvedValueOnce({
      data: [{ id: 2, url: 'https://new.example.com', interval_seconds: 30, created_at: '2026-01-01T00:00:00Z', owner_id: 1 }],
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    render(<Dashboard />);
    await waitFor(() => expect(mockedGetChecks).toHaveBeenCalledTimes(1));

    await userEvent.type(screen.getByLabelText(/URL/i), 'https://new.example.com');
    await userEvent.clear(screen.getByLabelText(/Intervall/i));
    await userEvent.type(screen.getByLabelText(/Intervall/i), '30');
    await userEvent.click(screen.getByRole('button', { name: /Check anlegen/i }));

    await waitFor(() =>
      expect(mockedCreateCheck).toHaveBeenCalledWith({ url: 'https://new.example.com', interval_seconds: 30 }),
    );
    await waitFor(() => expect(mockedGetChecks).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByText('https://new.example.com')).toBeInTheDocument());
  });

  it('zeigt eine Fehlermeldung, wenn das Laden der Checks fehlschlägt', async () => {
    mockedGetChecks.mockRejectedValue(new Error('network error'));

    render(<Dashboard />);

    await waitFor(() => expect(screen.getByText(/konnten nicht geladen werden/i)).toBeInTheDocument());
  });
});
