import { apiClient } from './client';
export const getReports = async () => (await apiClient.get('/reports')).data;
