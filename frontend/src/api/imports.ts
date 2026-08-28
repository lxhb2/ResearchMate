import { api } from './client'

export interface ImportPreviewEntry {
  title: string
  authors: string[]
  year: number | null
  doi: string
  journal: string
  tags: string[]
  has_pdf: boolean
}

export interface ImportPreview {
  ok: boolean
  errors: string[]
  entries: ImportPreviewEntry[]
  total: number
  attachments_found: number
}

export interface ImportResult {
  ok: boolean
  imported: { id: string; title: string; has_pdf: boolean; status: string }[]
  count: number
  with_pdf: number
  without_pdf: number
  skipped_duplicates: number
}

export type RelatedPaperRelation = 'reference' | 'citation' | 'similar'

export interface RelatedPaper {
  id: string
  title: string
  authors: string[]
  year: number | null
  doi: string
  abstract: string
  journal: string
  citation_count: number
  url: string
  relations: RelatedPaperRelation[]
  sources: string[]
}

export interface DoiRelatedResult {
  ok: boolean
  doi: string
  anchor: {
    title: string
    authors: string[]
    year: number | null
    doi: string
    journal: string
    citation_count: number
    url: string
  } | null
  papers: RelatedPaper[]
  errors: string[]
  sources: Record<string, { ok: boolean; count: number }>
}

export interface MetadataImportResult {
  ok: boolean
  imported: { id: string; title: string; doi: string | null; year: number | null }[]
  count: number
  skipped_duplicates: number
}

/** Zotero / BibTeX / RIS 导入（预览与导入分离，导入前先回显命中情况） */
export const importsApi = {
  zoteroPreview: async (dataDir: string): Promise<ImportPreview> => {
    const { data } = await api.post<ImportPreview>('/imports/zotero/preview', { data_dir: dataDir })
    return data
  },
  zoteroImport: async (dataDir: string): Promise<ImportResult> => {
    const { data } = await api.post<ImportResult>('/imports/zotero/import', { data_dir: dataDir })
    return data
  },
  bibtexPreview: async (content: string): Promise<ImportPreview> => {
    const { data } = await api.post<ImportPreview>('/imports/bibtex/preview', { content })
    return data
  },
  bibtexImport: async (content: string): Promise<ImportResult> => {
    const { data } = await api.post<ImportResult>('/imports/bibtex/import', { content })
    return data
  },
  risPreview: async (content: string): Promise<ImportPreview> => {
    const { data } = await api.post<ImportPreview>('/imports/ris/preview', { content })
    return data
  },
  risImport: async (content: string): Promise<ImportResult> => {
    const { data } = await api.post<ImportResult>('/imports/ris/import', { content })
    return data
  },

  doiRelated: async (query: string, limit = 24): Promise<DoiRelatedResult> => {
    const { data } = await api.post<DoiRelatedResult>('/papers/doi-related', { query, limit })
    return data
  },

  importRelated: async (papers: RelatedPaper[]): Promise<MetadataImportResult> => {
    const { data } = await api.post<MetadataImportResult>('/imports/metadata/import', { papers })
    return data
  },
}
