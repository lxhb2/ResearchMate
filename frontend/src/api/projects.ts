import { api } from './client'
import type { Project } from '../types'

export const projectsApi = {
  create: async (payload: { title?: string; outline?: unknown; content?: string }): Promise<Project> => {
    const { data } = await api.post<Project>('/projects', payload)
    return data
  },
  list: async (): Promise<Project[]> => {
    const { data } = await api.get<Project[]>('/projects')
    return data
  },
  get: async (id: string): Promise<Project> => {
    const { data } = await api.get<Project>(`/projects/${id}`)
    return data
  },
  update: async (id: string, payload: Partial<Project>): Promise<Project> => {
    const { data } = await api.put<Project>(`/projects/${id}`, payload)
    return data
  },
  remove: async (id: string): Promise<void> => {
    await api.delete(`/projects/${id}`)
  },

  generateTitle: async (id: string, direction: string): Promise<{ titles: string[] }> => {
    const { data } = await api.post(`/projects/${id}/generate-title`, { direction })
    return data
  },
  generateOutline: async (id: string, topic: string, notes?: string): Promise<{ outline: unknown }> => {
    const { data } = await api.post(`/projects/${id}/generate-outline`, { topic, notes })
    return data
  },
  searchMaterials: async (
    id: string,
    sectionTitles: string[],
    topK = 5,
  ): Promise<{ materials: Record<string, unknown[]> }> => {
    const { data } = await api.post(`/projects/${id}/search-materials`, {
      section_titles: sectionTitles,
      top_k: topK,
    })
    return data
  },
  generateDraft: async (
    id: string,
    outline: unknown,
    materialChunkIds: string[],
    section?: string,
  ): Promise<{ content: string }> => {
    const { data } = await api.post(`/projects/${id}/generate-draft`, {
      outline,
      material_chunk_ids: materialChunkIds,
      section,
    })
    return data
  },
  generateAbstract: async (id: string): Promise<{ abstract: string; keywords: string[] }> => {
    const { data } = await api.post(`/projects/${id}/generate-abstract`, {})
    return data
  },
  exportWordUrl: (id: string): string => `/api/v1/projects/${id}/export-word`,
}
