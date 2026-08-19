import { api, streamSSE } from './client'
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

  list: async (
    params: { search?: string; status?: string; tag?: string; page?: number; limit?: number } = {},
  ): Promise<PaperList> => {
    const { data } = await api.get<PaperList>('/papers', { params })
    return data
  },

  get: async (id: string): Promise<Paper> => {
    const { data } = await api.get<Paper>(`/papers/${id}`)
    return data
  },

  update: async (
    id: string,
    payload: { title?: string; authors?: string[]; year?: number; doi?: string; tags?: string[] },
  ): Promise<Paper> => {
    const { data } = await api.patch<Paper>(`/papers/${id}`, payload)
    return data
  },

  remove: async (id: string): Promise<void> => {
    await api.delete(`/papers/${id}`)
  },

  tags: async (): Promise<{ tags: { name: string; count: number }[] }> => {
    const { data } = await api.get<{ tags: { name: string; count: number }[] }>('/papers/tags')
    return data
  },

  citation: async (id: string, format: 'bibtex' | 'biblatex' | 'gb7714' = 'biblatex'): Promise<{ citation: string; format: string; filename: string }> => {
    const { data } = await api.get(`/papers/${id}/citation`, { params: { format } })
    return data
  },

  /** 批量导出选中文献为 BibTeX / RIS 文本 */
  exportPapers: async (ids: string[], format: 'bibtex' | 'ris' = 'bibtex') => {
    const { data } = await api.post<{ content: string; filename: string; format: string; count: number }>(
      '/papers/export',
      { ids, format },
    )
    return data
  },

  fileUrl: (id: string): string => `/api/v1/papers/${id}/file`,

  chat: async (id: string, message: string): Promise<{ answer: string }> => {
    const { data } = await api.post(`/papers/${id}/chat`, { message })
    return data
  },

  chatStream: async (
    id: string,
    message: string,
    onDelta: (delta: string) => void,
    onMeta?: (meta: { citations?: { page: number | null; snippet: string }[] }) => void,
  ): Promise<void> => {
    await streamSSE(
      `/papers/${id}/chat/stream`,
      { message },
      onDelta,
      undefined,
      undefined,
      onMeta,
    )
  },

  /** 恢复该论文的历史对话（进入阅读器时调用） */
  chatHistory: async (id: string): Promise<{ role: 'user' | 'assistant'; content: string }[]> => {
    const { data } = await api.get<{ messages: { role: 'user' | 'assistant'; content: string }[] }>(
      `/papers/${id}/chat/messages`,
    )
    return data.messages
  },

  /** 手动追加一条对话消息（划词解释等非 chat 通道的问答入档） */
  appendChat: async (id: string, role: 'user' | 'assistant', content: string): Promise<void> => {
    await api.post(`/papers/${id}/chat/messages`, { role, content })
  },

  /** 清空该论文的全部对话记录 */
  clearChat: async (id: string): Promise<void> => {
    await api.delete(`/papers/${id}/chat/messages`)
  },

  /** 保存阅读进度（当前页码） */
  saveProgress: async (id: string, page: number): Promise<void> => {
    await api.put(`/papers/${id}/progress`, { page })
  },

  summary: async (
    id: string,
    type: 'full' | 'chapter',
    chapter?: string,
    refresh = false,
  ): Promise<{ summary: string; cached: boolean }> => {
    const { data } = await api.post<{ summary: string; cached: boolean }>(`/papers/${id}/summary`, {
      type,
      chapter,
      refresh,
    })
    return data
  },

  analysis: async (id: string): Promise<PaperAnalysis> => {
    const { data } = await api.get<PaperAnalysis>(`/papers/${id}/analysis`)
    return data
  },

  /** 重新跑结构感知拆分 + 六维语义分析（无需重新上传 PDF） */
  reanalyze: async (id: string): Promise<{ ok: boolean }> => {
    const { data } = await api.post<{ ok: boolean }>(`/papers/${id}/reanalyze`)
    return data
  },

  /** 多文档综述生成（Q1-2）：SSE 流式，逐段 delta + 结束 citations 元事件 */
  literatureReview: async (
    opts: LitReviewOptions,
    onDelta: (delta: string) => void,
    onCitations?: (citations: ReviewCitation[]) => void,
    onDone?: (meta?: Record<string, unknown>) => void,
    signal?: AbortSignal,
  ): Promise<void> => {
    await streamSSE(
      '/papers/batch/literature-review',
      opts,
      onDelta,
      onDone,
      signal,
      (ev) => {
        if (Array.isArray(ev.citations)) onCitations?.(ev.citations as ReviewCitation[])
      },
    )
  },
}

export interface LitReviewOptions {
  paper_ids: string[]
  topic: string
  structure: 'thematic' | 'chronological' | 'gap_analysis'
  citation_style: 'apa' | 'gb7714' | 'bibtex_citekey'
}

export interface ReviewCitation {
  chunk_id: string
  paper_id: string
  paper_title: string | null
  page: number | null
  snippet: string
  citation: string
  anchor: string
}

export interface PaperAnalysisDimension {
  dimension: string
  label: string
  content: string
  page_number: number | null
  section: string | null
  meta: { mode?: string; keywords?: string[]; evidence_sections?: string[] } | null
}

export interface PaperAnalysisMeta {
  structure?: { title: string; level: number; kind: string; chars: number }[]
  top_level?: { title: string; kind: string; chars: number }[]
  chunking?: { text_chunks: number; mode: string; chunk_chars: number; overlap: number }
  split?: {
    mode: string
    dimension_count: number
    keywords?: string[]
    evidence?: Record<string, string[]>
  }
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
  analysis_status: 'pending' | 'done' | 'failed' | null
  dimensions: PaperAnalysisDimension[]
  analysis_meta: PaperAnalysisMeta | null
  user_notes: PaperAnalysisNote[]
}
