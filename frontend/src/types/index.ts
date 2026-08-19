export interface User {
  id: string
  username: string
  created_at: string
}

export interface Token {
  access_token: string
  token_type: string
  user: User
}

export interface Paper {
  id: string
  user_id: string
  title: string | null
  authors: string[] | null
  year: number | null
  doi: string | null
  abstract: string | null
  source: string
  file_path: string | null
  tags?: string[] | null
  status: 'processing' | 'ready' | 'error'
  /** AI 语义分析进度（六维拆分 + 向量化），与 status 解耦 */
  analysis_status?: 'pending' | 'done' | 'failed' | null
  /** AI 全文总结缓存（长期记忆：重开界面直接恢复） */
  summary?: string | null
  /** 上次阅读页码（长期记忆：重开阅读器自动恢复位置） */
  last_page?: number | null
  full_text?: string | null
  created_at: string
  updated_at: string
}

export interface PaperList {
  items: Paper[]
  total: number
  page: number
  limit: number
}

export interface SearchResultItem {
  chunk_id: string
  paper_id: string
  paper_title: string | null
  dimension:
    | 'title_keywords'
    | 'background'
    | 'method'
    | 'results'
    | 'conclusion'
    | 'contributions'
  content: string
  page_number: number | null
  score: number
}

export interface SearchResult {
  query: string
  items: SearchResultItem[]
}

export interface Annotation {
  id?: string
  user_id?: string
  paper_id: string
  type: 'highlight' | 'underline' | 'note' | 'summary' | 'ink'
  content: string | null
  page_number: number | null
  position: Record<string, unknown> | null
  color?: string | null
  comment?: string | null
  tags?: string[] | null
  created_at?: string
}

export interface Conversation {
  id: string
  title: string | null
  messages: { role: string; content: string }[]
  created_at: string
  updated_at: string
}

export interface ProjectSection {
  title: string
  points?: string[]
}

export interface Project {
  id: string
  user_id: string
  title: string | null
  outline: { sections: ProjectSection[] } | null
  content: string | null
  references: Record<string, unknown>[] | null
  step: number
  created_at: string
  updated_at: string
}
