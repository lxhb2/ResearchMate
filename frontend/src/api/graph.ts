import { api, streamSSE } from './client'

export interface GraphNodeData {
  id: string
  x: number
  y: number
  cluster: number
  paper_id: string
  paper_title: string
  dimension: string
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
