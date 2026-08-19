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
 *
 * 节点配置借鉴 n8n / Dify 的「参数与运行策略分离」：
 * - data.retry / data.retry_delay        → 节点级重试（n8n Retry On Fail）
 * - data.onError                         → 失败策略：stop（终止，默认）/ continue（用默认值继续）
 * - data.defaultValue                    → onError=continue 时的默认输出（Dify 默认值策略）
 */

export interface WhiteboardNodeMeta {
  nodeType: 'tool' | 'condition' | 'confirm' | 'end'
  tool?: string
  args?: Record<string, any>
  description?: string
  guide?: string
  stage?: string
  condition?: { variable: string; operator: string; value?: any }
  /** 运行策略（借鉴 n8n Settings Tab / Dify Retry Config） */
  retry?: number
  retryDelay?: number
  /** 失败策略：stop=终止（默认）；continue=使用默认值继续 */
  onError?: 'stop' | 'continue'
  /** onError=continue 时的默认输出 */
  defaultValue?: string
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  sourceHandle?: string | null
  /** 连线标签（条件分支显示 true/false；React Flow 的 Edge.label 允许 ReactNode，这里只关心字符串） */
  label?: string | null
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

/** 工具 → 主要输出字段（供变量选择器与默认值提示） */
export const TOOL_OUTPUT_FIELDS: Record<string, { key: string; label: string }[]> = {
  paper_parse: [
    { key: 'paper_id', label: '论文 ID' },
    { key: 'title', label: '标题' },
    { key: 'abstract', label: '摘要' },
    { key: 'full_text', label: '全文' },
  ],
  rag_search: [
    { key: 'count', label: '命中条数' },
    { key: 'hits', label: '检索片段列表' },
  ],
  llm_translate: [{ key: 'translation', label: '译文' }],
  note_append: [
    { key: 'ok', label: '是否成功' },
    { key: 'project_id', label: '项目 ID' },
  ],
  llm_compare: [
    { key: 'table', label: '对比表格' },
    { key: 'summary', label: '对比总结' },
  ],
  citation_generate: [{ key: 'references', label: '引用列表' }],
  paper_summarize: [
    { key: 'summary', label: '总结' },
    { key: 'contributions', label: '贡献列表' },
    { key: 'keywords', label: '关键词' },
  ],
  library_list: [
    { key: 'count', label: '论文总数' },
    { key: 'papers', label: '论文列表' },
  ],
  data_analyze: [
    { key: 'code', label: '生成的代码' },
    { key: 'result', label: '执行结果' },
  ],
  experiment_plan: [{ key: 'plan', label: '实验方案' }],
}

/** 找出给定节点的全部上游节点（沿边反向遍历，含自身），供变量选择器列出可用引用 */
export function upstreamNodes(nodes: GraphNode[], edges: GraphEdge[], nodeId: string): GraphNode[] {
  const rev = new Map<string, string[]>()
  edges.forEach((e) => {
    const list = rev.get(e.target) || []
    list.push(e.source)
    rev.set(e.target, list)
  })
  const seen = new Set<string>([nodeId])
  const order: GraphNode[] = []
  const walk = (id: string) => {
    for (const src of rev.get(id) || []) {
      if (seen.has(src)) continue
      seen.add(src)
      walk(src)
      const n = nodes.find((x) => x.id === src)
      if (n) order.push(n)
    }
  }
  walk(nodeId)
  return order
}

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

  // 节点级校验（借鉴 n8n：必填参数为空时节点标红，保存时列出清单）
  for (const n of nodes) {
    const d: any = n.data || {}
    const label = d.label || n.id
    if (d.nodeType === 'tool') {
      if (!TOOL_NODES.has(d.tool || '')) {
        errors.push(`节点「${label}」使用了未知工具：${d.tool || '（空）'}`)
      }
      // 必填参数校验（与 TOOL_ARGS_DEF.required 对齐）
      const missing = requiredArgsOf(d.tool).filter((k) => {
        const v = (d.args || {})[k]
        return v === undefined || v === null || v === ''
      })
      if (missing.length) {
        errors.push(`节点「${label}」缺少必填参数：${missing.join('、')}`)
      }
    } else if (d.nodeType === 'condition') {
      const variable = d.condition?.variable
      if (!variable) errors.push(`条件节点「${label}」未设置判断变量`)
      // 条件节点必须同时接 true/false 分支之一
      const outs = edges.filter((e) => e.source === n.id)
      if (!outs.some((e) => e.sourceHandle === 'true') && !outs.some((e) => e.sourceHandle === 'false')) {
        errors.push(`条件节点「${label}」未连接任何分支（true/false）`)
      }
      if (!outs.some((e) => e.sourceHandle === 'false')) {
        // 允许只接 true 分支（无匹配即结束），不视为错误
      }
    } else if (d.nodeType === 'end') {
      // end 无需校验
    }
    // 错误策略为「继续」时必须提供默认值
    if ((d.nodeType === 'tool') && d.onError === 'continue' && (d.defaultValue || '').toString().trim() === '') {
      errors.push(`节点「${label}」设置了失败继续，但未填写默认输出值`)
    }
  }
  return errors
}

/** 各工具的必填参数（与 WhiteboardView.TOOL_ARGS_DEF 保持一致） */
const REQUIRED_ARGS: Record<string, string[]> = {
  rag_search: ['query'],
  llm_translate: ['text'],
  note_append: ['content'],
  llm_compare: ['query'],
  data_analyze: ['question'],
  experiment_plan: ['question'],
}

export function requiredArgsOf(tool?: string): string[] {
  return REQUIRED_ARGS[tool || ''] || []
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
      // 运行策略（借鉴 n8n Settings / Dify retry_config）
      const retry = Number(meta_.retry ?? 0)
      base.retry = Number.isFinite(retry) && retry > 0 ? Math.min(Math.floor(retry), 5) : 0
      if (base.retry > 0) {
        const delay = Number(meta_.retryDelay ?? 1)
        base.retry_delay = Number.isFinite(delay) && delay > 0 ? Math.min(delay, 30) : 1
      }
      // 失败策略：stop=抛错终止（引擎默认）；continue=落为默认值
      if (meta_.onError === 'continue') {
        base.on_error = 'continue'
        base.default_value = (meta_.defaultValue ?? '').toString()
      }
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
