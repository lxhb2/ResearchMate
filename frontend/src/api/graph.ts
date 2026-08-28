import { api, streamSSE } from './client'

export interface GraphNodeData {
  id: string
  x: number
  y: number
  cluster: number
  paper_id: string
  paper_title: string
  dimension: string
  section: string | null
  page_number: number | null
  snippet: string
}

export interface GraphClusterInfo {
  id: number
  label: string
  keywords: string[]
  color: string
  count: number
  papers: number
}

export interface GraphEdgeData {
  source: string
  target: string
  sim: number
}

export interface SmartGraph {
  ok: boolean
  mode: 'embedding' | 'keyword'
  total_chunks: number
  node_count: number
  clusters: GraphClusterInfo[]
  nodes: GraphNodeData[]
  edges: GraphEdgeData[]
}

export interface BibliometricNode {
  id: string
  label: string
  value: number
  cluster: number
  x: number
  y: number
  extra: {
    authors?: string[]
    year?: number | null
    citation_count?: number
    degree?: number
    papers?: number
    doi?: string | null
    paper_id?: string
    reference_count?: number
    [key: string]: unknown
  }
}

export interface BibliometricEdge {
  source: string
  target: string
  weight: number
  kinds?: ('citation' | 'similar')[]
}

export interface BibliometricGraph {
  ok: boolean
  network_type: 'co_authorship' | 'co_occurrence' | 'citation' | 'bibliographic_coupling' | 'paper_similarity'
  network_label: string
  source: 'library' | 'external'
  external_source: string | null
  enrichment_source: string | null
  paper_count: number
  node_count: number
  edge_count: number
  cluster_resolution: number
  directed: boolean
  nodes: BibliometricNode[]
  edges: BibliometricEdge[]
  clusters: GraphClusterInfo[]
}

export interface BibliometricParams {
  network_type: BibliometricGraph['network_type']
  source: 'library' | 'external'
  query?: string
  external_source?: string
  limit?: number
  cluster_resolution?: number
}

export interface AnalyzeSource {
  index: number
  paper_id: string
  paper_title: string
  page: number | null
}

/** Smart Graph 语义聚类图谱 */
export const graphApi = {
  smart: async (limit = 400): Promise<SmartGraph> => {
    const { data } = await api.get<SmartGraph>('/graph/smart', { params: { limit } })
    return data
  },

  bibliometric: async (params: BibliometricParams): Promise<BibliometricGraph> => {
    const { data } = await api.get<BibliometricGraph>('/graph/bibliometric', { params })
    return data
  },

  exportVOSviewer: async (params: BibliometricParams): Promise<Blob> => {
    const response = await api.get('/graph/bibliometric/export', {
      params,
      responseType: 'blob',
    })
    return response.data as Blob
  },

  /** 框选批量分析（SSE 流式），结束后通过 onSources 收到来源列表 */
  analyzeStream: async (
    chunkIds: string[],
    question: string,
    onDelta: (delta: string) => void,
    onSources?: (sources: AnalyzeSource[]) => void,
  ): Promise<void> => {
    await streamSSE(
      '/graph/analyze',
      { chunk_ids: chunkIds, question },
      onDelta,
      undefined,
      undefined,
      (ev) => {
        if (Array.isArray(ev.sources)) onSources?.(ev.sources as AnalyzeSource[])
      },
    )
  },
}
