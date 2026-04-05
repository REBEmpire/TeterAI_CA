<<<<<<< SEARCH
  updateSettings: (data: Partial<UserSettings>) =>
    apiClient.post('/settings', data).then(res => res.data),
=======
  updateSettings: (data: Partial<UserSettings>) =>
    apiClient.post('/settings', data).then(res => res.data),

  getHealth: () =>
    apiClient.get('/health').then(res => res.data),

  retryTask: (taskId: string) =>
    apiClient.post(`/tasks/${taskId}/retry`).then(res => res.data),
>>>>>>> REPLACE
