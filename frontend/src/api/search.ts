import { api, streamSSE } from './client'
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

export interface PinCard {
  id: string
  paper_id: string
  paper_title: string
  authors: string[]
  year: number | null
  type: string
  snippet: string
  note: string
  color: string
  page: number | null
  anchor: string
  created_at: string | null
  card_order: number
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
  update: async (
    id: string,
    payload: { content?: string; comment?: string; color?: string; tags?: string[]; position?: Record<string, unknown> },
  ): Promise<Annotation> => {
    const { data } = await api.patch<Annotation>(`/annotations/${id}`, payload)
    return data
  },
  // ---- Pin 卡片笔记（Q1-1）----
  /** 全部「卡片笔记」（带笔记的标注 + 文献元数据 + 引用锚文本） */
  listPinCards: async (): Promise<PinCard[]> => {
    const { data } = await api.get<PinCard[]>('/annotations/pins')
    return data
  },
  /** 拖拽重排：写入每张卡片的排序号 */
  reorder: async (items: { id: string }[]): Promise<{ ok: boolean; updated: number }> => {
    const { data } = await api.post('/annotations/reorder', { items })
    return data
  },
  /** 发送到写作项目：把卡片内容追加到指定项目，自动带引用锚文本 */
  sendToWriting: async (annotationId: string, projectId: string): Promise<{ ok: boolean; anchor: string; content: string }> => {
    const { data } = await api.post(`/annotations/${annotationId}/send-to-writing`, { project_id: projectId })
    return data
  },
}

export const translateApi = {
  translate: async (text: string, targetLang = 'zh'): Promise<{ translation: string }> => {
    const { data } = await api.post('/translate', { text, target_lang: targetLang })
    return data
  },
  // 流式翻译
  translateStream: async (text: string, targetLang: string, onDelta: (delta: string) => void): Promise<void> => {
    await streamSSE('/translate/stream', { text, target_lang: targetLang }, onDelta)
  },
}

export const termApi = {
  lookup: async (text: string, webSearch = false): Promise<{ explanation: string }> => {
    const { data } = await api.post('/term/lookup', { text, web_search: webSearch })
    return data
  },
  // 流式术语解释
  lookupStream: async (text: string, webSearch: boolean, onDelta: (delta: string) => void): Promise<void> => {
    await streamSSE('/term/lookup/stream', { text, web_search: webSearch }, onDelta)
  },
}
