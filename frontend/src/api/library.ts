import { apiClient } from './client';
export const getImages = async () => (await apiClient.get('/library/images')).data;
