import { api } from './client'
import type { Paper, PaperList } from '../types'

export const papersApi = {
  upload: async (file: File): Promise<Paper> => {
    const form = new FormData()
    form.append('file', file)
    const { data } = await api.post<Paper>('/papers/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
  },

  list: async (params: { search?: string; status?: string; page?: number; limit?: number } = {}): Promise<PaperList> => {
    const { data } = await api.get<PaperList>('/papers', { params })
    return data
  },

  get: async (id: string): Promise<Paper> => {
    const { data } = await api.get<Paper>(`/papers/${id}`)
    return data
  },

  remove: async (id: string): Promise<void> => {
    await api.delete(`/papers/${id}`)
  },

  fileUrl: (id: string): string => `/api/v1/papers/${id}/file`,

  chat: async (id: string, message: string): Promise<{ answer: string }> => {
    const { data } = await api.post(`/papers/${id}/chat`, { message })
    return data
  },

  summary: async (id: string, type: 'full' | 'chapter', chapter?: string): Promise<{ summary: string }> => {
    const { data } = await api.post(`/papers/${id}/summary`, { type, chapter })
    return data
  },

  analysis: async (id: string): Promise<PaperAnalysis> => {
    const { data } = await api.get<PaperAnalysis>(`/papers/${id}/analysis`)
    return data
  },
}

export interface PaperAnalysisDimension {
  dimension: string
  label: string
  content: string
  page_number: number | null
}

export interface PaperAnalysisNote {
  id: string
  type: 'highlight' | 'underline' | 'note' | 'summary'
  content: string | null
  page_number: number | null
  created_at: string | null
}

export interface PaperAnalysis {
  paper_id: string
  title: string | null
  status: string
  dimensions: PaperAnalysisDimension[]
  user_notes: PaperAnalysisNote[]
}
