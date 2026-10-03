import { apiClient } from './client';
export const exportJob = async (jobId: string) => (await apiClient.get(`/export/${jobId}`, { responseType: 'blob' })).data;
