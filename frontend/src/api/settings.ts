import { apiClient } from './client';
export const getSettings = async () => (await apiClient.get('/settings')).data;
export const updateSettings = async (data: any) => (await apiClient.put('/settings', data)).data;
