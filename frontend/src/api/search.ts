import { api } from './client'
import type { SearchResult, Annotation } from '../types'

export const searchApi = {
  semantic: async (query: string, topK = 5, dimension?: string): Promise<SearchResult> => {
    const { data } = await api.post<SearchResult>('/search/semantic', {
      query,
      top_k: topK,
      dimension,
    })
    return data
  },
}

export const annotationsApi = {
  create: async (payload: Omit<Annotation, 'id' | 'user_id' | 'created_at'>): Promise<Annotation> => {
    const { data } = await api.post<Annotation>('/annotations', payload)
    return data
  },
  list: async (paperId?: string, type?: string): Promise<Annotation[]> => {
    const { data } = await api.get<Annotation[]>('/annotations', {
      params: { paper_id: paperId, type },
    })
    return data
  },
  remove: async (id: string): Promise<void> => {
    await api.delete(`/annotations/${id}`)
  },
}

export const translateApi = {
  translate: async (text: string, targetLang = 'zh'): Promise<{ translation: string }> => {
    const { data } = await api.post('/translate', { text, target_lang: targetLang })
    return data
  },
}

export const termApi = {
  lookup: async (text: string, webSearch = false): Promise<{ explanation: string }> => {
    const { data } = await api.post('/term/lookup', { text, web_search: webSearch })
    return data
  },
}
