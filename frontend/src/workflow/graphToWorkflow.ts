/**
 * 白板/对话工作流 → 可执行 schema 的转换器。
 *
 * React Flow（白板）顶层结构为 { nodes: [], edges: [] }（通用图）。
 * 后端执行引擎（executor.py）使用 { start, nodes: {id:{...}}, output }（字典 + next 指针）。
 * 本模块把「通用图」转换为「执行 schema」，从而复用已跑通的后端执行引擎。
 *
 * 约定：
 * - 每个白板节点 data.nodeType: tool / condition / confirm / end
 * - condition 节点用两条出边区分：sourceHandle="true"→next_if_true，sourceHandle="false"→next_if_false
 * - 其余节点用默认出边（sourceHandle 为空）作为 next
 * - 入度为 0 的节点作为 start；type=end 的节点作为 output
 */

export interface WhiteboardNodeMeta {
  nodeType: 'tool' | 'condition' | 'confirm' | 'end'
  tool?: string
  args?: Record<string, any>
  description?: string
  guide?: string
  stage?: string
  condition?: { variable: string; operator: string; value?: any }
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  sourceHandle?: string | null
}

export interface GraphNode {
  id: string
  data?: any
}

export interface WorkflowSchema {
  workflow_id: string
  name: string
  description: string
  start: string
  nodes: Record<string, any>
  output: string | null
}

const TOOL_NODES = new Set([
  'paper_parse',
  'rag_search',
  'llm_translate',
  'note_append',
  'llm_compare',
  'citation_generate',
  'paper_summarize',
  'library_list',
  'data_analyze',
  'experiment_plan',
])

export function validateGraph(nodes: GraphNode[], edges: GraphEdge[]): string[] {
  const errors: string[] = []
  if (!nodes.length) {
    errors.push('画布为空，请先拖入至少一个节点')
    return errors
  }
  const ids = new Set(nodes.map((n) => n.id))
  const hasIncoming = new Set<string>()
  edges.forEach((e) => {
    hasIncoming.add(e.target)
    if (!ids.has(e.source)) errors.push(`连线 ${e.id} 的起点节点不存在`)
    if (!ids.has(e.target)) errors.push(`连线 ${e.id} 的终点节点不存在`)
  })
  const starts = nodes.filter((n) => !hasIncoming.has(n.id))
  if (starts.length === 0) errors.push('工作流存在环路或缺少起始节点（无入边的节点）')
  const hasEnd = nodes.some((n) => n.data?.nodeType === 'end')
  if (!hasEnd) errors.push('缺少「结束」节点')
  return errors
}

export function graphToWorkflow(
  nodes: GraphNode[],
  edges: GraphEdge[],
  meta: { name?: string; description?: string } = {},
): WorkflowSchema {
  const valid = validateGraph(nodes, edges)
  if (valid.length) {
    throw new Error(valid.join('；'))
  }

  const ids = new Set(nodes.map((n) => n.id))
  const hasIncoming = new Set<string>()
  edges.forEach((e) => hasIncoming.add(e.target))

  const outNodes: Record<string, any> = {}
  const outEdges: Record<string, GraphEdge[]> = {}
  edges.forEach((e) => {
    ;(outEdges[e.source] = outEdges[e.source] || []).push(e)
  })

  for (const n of nodes) {
    const meta_: any = n.data || {}
    const base: any = {
      id: n.id,
      type: meta_.nodeType || 'tool',
      description: meta_.description || '',
      guide: meta_.guide || undefined,
      stage: meta_.stage || undefined,
    }

    if (base.type === 'tool') {
      base.tool = meta_.tool
      if (!TOOL_NODES.has(meta_.tool || '')) {
        throw new Error(`节点 ${n.id} 使用了未知工具：${meta_.tool}`)
      }
      base.args = meta_.args || {}
    } else if (base.type === 'condition') {
      base.condition = meta_.condition || { variable: '', operator: 'exists', value: null }
    } else if (base.type === 'end') {
      base.type = 'end'
    } else if (base.type === 'confirm') {
      base.type = 'confirm'
    }

    // 流转
    const outs = outEdges[n.id] || []
    if (base.type === 'condition') {
      const trueEdge = outs.find((e) => e.sourceHandle === 'true')
      const falseEdge = outs.find((e) => e.sourceHandle === 'false')
      if (trueEdge) base.next_if_true = trueEdge.target
      if (falseEdge) base.next_if_false = falseEdge.target
    } else {
      const nextEdge = outs.find((e) => !e.sourceHandle) || outs[0]
      if (nextEdge) base.next = nextEdge.target
    }

    outNodes[n.id] = base
  }

  // 起始节点 = 入度为 0 的第一个节点
  const start = nodes.find((n) => !hasIncoming.has(n.id))!.id
  // 结束节点 = 第一个 type=end
  const endNode = nodes.find((n) => n.data?.nodeType === 'end')
  const output = endNode ? endNode.id : null

  return {
    workflow_id: '',
    name: meta.name || '我的白板工作流',
    description: meta.description || '',
    start,
    nodes: outNodes,
    output,
  }
}