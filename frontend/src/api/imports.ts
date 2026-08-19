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
}
