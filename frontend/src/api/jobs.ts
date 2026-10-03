import { apiClient } from './client';
export const getJobs = async () => (await apiClient.get('/jobs')).data;
export const getJob = async (id: string) => (await apiClient.get(`/jobs/${id}`)).data;
export const createJob = async (data: any) => (await apiClient.post('/jobs', data)).data;
export const cancelJob = async (id: string) => (await apiClient.post(`/jobs/${id}/cancel`)).data;
