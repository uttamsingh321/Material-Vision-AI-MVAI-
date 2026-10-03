import { apiClient } from './client';
export const getUsers = async () => (await apiClient.get('/users')).data;
