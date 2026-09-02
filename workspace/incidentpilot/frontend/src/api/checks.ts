import api from './client';

export const getChecks = async () => {
  try {
    return await api.get('/checks');
  } catch (error) {
    console.error('Error fetching checks:', error);
    throw error;
  }
};

export const getCheckStatus = async (id: number) => {
  try {
    return await api.get(`/checks/${id}/status`);
  } catch (error) {
    console.error(`Error fetching status for check ${id}:`, error);
    throw error;
  }
};

export const createCheck = async (data: { url: string; interval_seconds: number }) => {
  try {
    return await api.post('/checks', data);
  } catch (error) {
    console.error('Error creating check:', error);
    throw error;
  }
};
