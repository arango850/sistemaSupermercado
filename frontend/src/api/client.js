import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export const getSummary              = ()     => api.get('/summary')
export const getTimeSeries           = ()     => api.get('/charts/time-series')
export const getBoxplot              = ()     => api.get('/charts/boxplot')
export const getHeatmap              = ()     => api.get('/charts/heatmap')
export const getSegments             = ()     => api.get('/segments')
export const getRecommendations      = ()     => api.get('/recommendations/category')
export const getRecommendationsByCategory = (name) =>
  api.get('/recommendations/category', { params: { name } })
export const runAnalysis             = ()     => api.post('/analysis/run')
export const getAnalysisStatus       = ()     => api.get('/analysis/status')

export default api
