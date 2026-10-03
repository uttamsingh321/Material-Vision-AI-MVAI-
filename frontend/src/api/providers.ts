import { apiClient } from './client';
export const getProviders = async () => (await apiClient.get('/providers/status')).data;
