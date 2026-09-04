import api from './client';
import type { Check, CheckStatus, NewCheck } from '../types';

export const getChecks = async () => {
  try {
    return await api.get<Check[]>('/checks');
  } catch (error) {
    console.error('Error fetching checks:', error);
    throw error;
  }
};

export const getCheckStatus = async (id: number) => {
  try {
    return await api.get<CheckStatus>(`/checks/${id}/status`);
  } catch (error) {
    console.error(`Error fetching status for check ${id}:`, error);
    throw error;
  }
};

export const createCheck = async (data: NewCheck) => {
  try {
    return await api.post<Check>('/checks', data);
  } catch (error) {
    console.error('Error creating check:', error);
    throw error;
  }
};
