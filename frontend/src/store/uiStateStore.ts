import { create } from 'zustand'

const STORAGE_KEY = 'researchmate_ui_state_v1'

export interface ReaderSnapshot {
  paperId: string
  page: number
  tab: string
  title: string
}

export interface PdfTaskSnapshot {
  paperId: string
  taskId: string
  engine: string
  status: string
  progress: number
  stage: string
}

interface UiState {
  reader: ReaderSnapshot | null
  pdfTask: PdfTaskSnapshot | null
  setReader: (reader: ReaderSnapshot | null) => void
  setPdfTask: (task: PdfTaskSnapshot | null) => void
}

function loadState(): Pick<UiState, 'reader' | 'pdfTask'> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { reader: null, pdfTask: null }
    const data = JSON.parse(raw)
    return {
      reader: data?.reader || null,
      pdfTask: data?.pdfTask || null,
    }
  } catch {
    return { reader: null, pdfTask: null }
  }
}

function persist(state: Pick<UiState, 'reader' | 'pdfTask'>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    /* 本地存储不可用时忽略 */
  }
}

const initial = loadState()

export const useUiStateStore = create<UiState>((set) => ({
  reader: initial.reader,
  pdfTask: initial.pdfTask,
  setReader: (reader) =>
    set((s) => {
      const next = { ...s, reader }
      persist(next)
      return next
    }),
  setPdfTask: (pdfTask) =>
    set((s) => {
      const next = { ...s, pdfTask }
      persist(next)
      return next
    }),
}))
