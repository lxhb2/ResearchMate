import { useCallback, useMemo, useRef, useState } from 'react'
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
  type Node,
  type Edge,
  type Connection,
  type NodeTypes,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  Button,
  Space,
  Typography,
  Input,
  Select,
  InputNumber,
  Divider,
  message,
  Tag,
  Empty,
  Alert,
} from 'antd'
import {
  ArrowLeftOutlined,
  SaveOutlined,
  SearchOutlined,
  FilePdfOutlined,
  ThunderboltOutlined,
  TranslationOutlined,
  ColumnWidthOutlined,
  HighlightOutlined,
  UnorderedListOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  BranchesOutlined,
  CheckCircleOutlined,
  MinusCircleOutlined,
} from '@ant-design/icons'
import { workflowApi } from '../api/workflow'
import { getErrorMessage } from '../api/client'
import { graphToWorkflow, validateGraph, type WhiteboardNodeMeta } from './graphToWorkflow'

const { Text, Paragraph } = Typography

/** 学术节点面板：拖拽到画布即可创建对应的工具/逻辑/控制节点 */
const NODE_PALETTE: {
  key: string
  label: string
  desc: string
  nodeType: WhiteboardNodeMeta['nodeType']
  tool?: string
  args?: Record<string, any>
  icon: React.ReactNode
  color: string
}[] = [
  { key: 'rag_search', label: '文献检索', desc: '在文献库按语义检索片段', nodeType: 'tool', tool: 'rag_search', args: { query: '', top_k: 5 }, icon: <SearchOutlined />, color: '#1677ff' },
  { key: 'paper_parse', label: 'PDF 解析', desc: '解析 PDF 并拆分语义维度', nodeType: 'tool', tool: 'paper_parse', args: {}, icon: <FilePdfOutlined />, color: '#fa8c16' },
  { key: 'paper_summarize', label: '大模型总结', desc: '对论文做全文/章节总结', nodeType: 'tool', tool: 'paper_summarize', args: { type: 'full' }, icon: <ThunderboltOutlined />, color: '#722ed1' },
  { key: 'llm_translate', label: '翻译', desc: '调用大模型翻译文本', nodeType: 'tool', tool: 'llm_translate', args: { text: '' }, icon: <TranslationOutlined />, color: '#13c2c2' },
  { key: 'llm_compare', label: '对比分析', desc: '对比两篇论文/方法', nodeType: 'tool', tool: 'llm_compare', args: {}, icon: <ColumnWidthOutlined />, color: '#eb2f96' },
  { key: 'note_append', label: '追加笔记', desc: '把结果写入项目笔记', nodeType: 'tool', tool: 'note_append', args: {}, icon: <HighlightOutlined />, color: '#52c41a' },
  { key: 'citation_generate', label: '生成引用', desc: '生成引用信息', nodeType: 'tool', tool: 'citation_generate', args: {}, icon: <UnorderedListOutlined />, color: '#2f54eb' },
  { key: 'library_list', label: '文献列表', desc: '列出文献库中的论文', nodeType: 'tool', tool: 'library_list', args: {}, icon: <DatabaseOutlined />, color: '#08979c' },
  { key: 'data_analyze', label: '数据分析', desc: '统计分析实验数据', nodeType: 'tool', tool: 'data_analyze', args: { data: '' }, icon: <DatabaseOutlined />, color: '#d46b08' },
  { key: 'experiment_plan', label: '实验方案', desc: '生成实验设计建议', nodeType: 'tool', tool: 'experiment_plan', args: { topic: '' }, icon: <ExperimentOutlined />, color: '#531dab' },
  { key: 'condition', label: '条件判断', desc: '按条件分叉执行', nodeType: 'condition', icon: <BranchesOutlined />, color: '#faad14' },
  { key: 'confirm', label: '人工确认', desc: '暂停等待用户确认', nodeType: 'confirm', icon: <CheckCircleOutlined />, color: '#f5222d' },
  { key: 'end', label: '结束', desc: '工作流终点', nodeType: 'end', icon: <MinusCircleOutlined />, color: '#8c8c8c' },
]

const TOOL_ARGS_DEF: Record<string, { name: string; label: string; type: 'text' | 'number' | 'select' | 'textarea'; options?: { label: string; value: string }[] }[]> = {
  rag_search: [
    { name: 'query', label: '检索语句', type: 'textarea' },
    { name: 'top_k', label: '返回条数 top_k', type: 'number' },
    { name: 'dimension', label: '维度', type: 'select', options: [
      { label: '不限', value: '' }, { label: '标题与关键词', value: 'title_keywords' }, { label: '研究背景', value: 'background' },
      { label: '方法/模型', value: 'method' }, { label: '实验结果', value: 'results' }, { label: '结论', value: 'conclusion' }, { label: '创新点', value: 'contributions' },
    ] },
  ],
  paper_parse: [{ name: 'paper_id', label: '论文 ID', type: 'text' }],
  paper_summarize: [{ name: 'type', label: '总结类型', type: 'select', options: [{ label: '全文', value: 'full' }, { label: '章节', value: 'chapter' }] }],
  llm_translate: [{ name: 'text', label: '待翻译文本', type: 'textarea' }],
  data_analyze: [{ name: 'data', label: '实验数据', type: 'textarea' }],
  experiment_plan: [{ name: 'topic', label: '研究主题', type: 'text' }],
}

const NODE_COLOR: Record<string, string> = {
  tool: '#1677ff',
  condition: '#faad14',
  confirm: '#f5222d',
  end: '#8c8c8c',
}

function NodeShell({ data, handles, children }: { data: any; handles: React.ReactNode; children?: React.ReactNode }) {
  const d = data as any
  const color = NODE_COLOR[d.nodeType] || '#1677ff'
  return (
    <div
      style={{
        border: `1px solid ${color}`,
        borderRadius: 10,
        background: '#fff',
        padding: '8px 12px',
        minWidth: 150,
        boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
        fontSize: 12,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ color, fontSize: 14 }}>{d.icon}</span>
        <Text strong style={{ fontSize: 12 }}>{d.label}</Text>
      </div>
      <div style={{ marginTop: 2, color: '#8c8c8c', fontSize: 11, whiteSpace: 'pre-wrap' }}>
        {d.summary || (children ?? '')}
      </div>
      {handles}
    </div>
  )
}

function BaseHandle({ data, sourceHandles }: { data: any; sourceHandles?: boolean }) {
  return (
    <>
      <Handle type="target" position={Position.Left} style={{ background: '#555' }} />
      {sourceHandles && (
        <Handle type="source" position={Position.Right} style={{ background: '#555' }} />
      )}
    </>
  )
}

function ToolNode({ data }: NodeProps) {
  const d = data as any
  return (
    <NodeShell data={d} handles={<BaseHandle data={d} sourceHandles />}>
      {d.summary || ''}
    </NodeShell>
  )
}

function ConditionNode({ data }: NodeProps) {
  const d = data as any
  return (
    <NodeShell data={d} handles={<>
      <Handle type="target" position={Position.Left} style={{ background: '#555' }} />
      <Handle type="source" id="true" position={Position.Right} style={{ background: '#52c41a', top: '30%' }} />
      <Handle type="source" id="false" position={Position.Right} style={{ background: '#f5222d', top: '70%' }} />
    </>}>
      {d.conditionSummary || '未设置条件'}
    </NodeShell>
  )
}

function ConfirmNode({ data }: NodeProps) {
  const d = data as any
  return (
    <NodeShell data={d} handles={<BaseHandle data={d} sourceHandles />}>
      {d.summary || '人工确认关卡'}
    </NodeShell>
  )
}

function EndNode({ data }: NodeProps) {
  return <NodeShell data={data as any} handles={<BaseHandle data={data as any} />} />
}

const nodeTypes: NodeTypes = {
  tool: ToolNode,
  condition: ConditionNode,
  confirm: ConfirmNode,
  end: EndNode,
}

function makeNodeFromPalette(p: (typeof NODE_PALETTE)[number], id: string, x: number, y: number): Node {
  const data: any = {
    nodeType: p.nodeType,
    label: p.label,
    icon: p.icon,
    color: p.color,
    tool: p.tool || '',
    args: p.args || {},
  }
  if (p.nodeType === 'condition') {
    data.variable = ''
    data.operator = 'exists'
    data.value = ''
    data.conditionSummary = '未设置条件'
  } else if (p.nodeType === 'confirm') {
    data.guide = ''
    data.stage = ''
    data.summary = '人工确认关卡'
  } else if (p.nodeType === 'end') {
    data.summary = '工作流结束'
  } else {
    data.summary = summarizeTool(p)
  }
  return { id, type: p.nodeType, position: { x, y }, data }
}

function summarizeTool(p: (typeof NODE_PALETTE)[number]): string {
  const args = p.args || {}
  const parts = Object.entries(args)
    .filter(([k, v]) => v !== '' && v != null)
    .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`)
  return parts.length ? parts.join(', ') : '点击右侧编辑参数'
}

export default function WhiteboardView({ onBack }: { onBack: () => void }) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null)
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [selected, setSelected] = useState<Node | null>(null)
  const [name, setName] = useState('我的白板工作流')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState<string[]>([])

  const validate = () => {
    const errs = validateGraph(nodes, edges)
    setErrors(errs)
    return errs.length === 0
  }

  const onConnect = useCallback(
    (conn: Connection) => setEdges((eds) => addEdge(conn, eds)),
    [setEdges],
  )

  const onNodeClick = useCallback((_: any, node: Node) => setSelected(node), [])

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }, [])

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      const key = e.dataTransfer.getData('application/researchmate-node')
      if (!key) return
      const p = NODE_PALETTE.find((n) => n.key === key)
      if (!p) return
      const pos = reactFlowWrapper.current
        ? (reactFlowWrapper.current as any).getBoundingClientRect()
        : { left: 0, top: 0 }
      const x = e.clientX - pos.left - 75
      const y = e.clientY - pos.top - 20
      const id = `${p.key}-${Date.now()}`
      setNodes((nds) => nds.concat(makeNodeFromPalette(p, id, x, y)))
    },
    [setNodes],
  )

  const onDragStart = useCallback((e: React.DragEvent, p: (typeof NODE_PALETTE)[number]) => {
    e.dataTransfer.setData('application/researchmate-node', p.key)
    e.dataTransfer.effectAllowed = 'move'
  }, [])

  const updateSelected = (patch: Partial<any>) => {
    if (!selected) return
    setNodes((nds) =>
      nds.map((n) => (n.id === selected.id ? { ...n, data: { ...n.data, ...patch } } : n)),
    )
    setSelected((s) => (s ? { ...s, data: { ...s.data, ...patch } } : s))
  }

  const updateArg = (name: string, value: any) => {
    if (!selected) return
    const args = { ...(selected.data.args || {}), [name]: value }
    const data: any = { ...selected.data, args }
    data.summary = Object.entries(args).filter(([k, v]) => v !== '' && v != null).map(([k, v]) => `${k}=${v}`).join(', ') || '点击编辑参数'
    updateSelected({ args, summary: data.summary })
  }

  const updateCondition = (patch: Partial<{ variable: string; operator: string; value: any }>) => {
    if (!selected) return
    const cond = { ...(selected.data.condition || {}), ...patch }
    const summary = `${cond.variable || '?'} ${cond.operator} ${cond.value ?? ''}`
    updateSelected({ condition: cond, conditionSummary: summary })
  }

  const saveAsTemplate = async () => {
    if (!validate()) return
    setSaving(true)
    try {
      const wf = graphToWorkflow(nodes, edges, { name, description })
      await workflowApi.saveTemplate({ name, description, workflow_json: wf })
      message.success('工作流已保存为「我的模板」，可在模板库中选择运行')
      onBack()
    } catch (err) {
      message.error('保存失败：' + getErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const exportJson = () => {
    const blob = new Blob([JSON.stringify({ name, description, nodes, edges }, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${name || 'workflow'}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const importJson = (file: File) => {
    const reader = new FileReader()
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result))
        if (parsed.nodes) setNodes(parsed.nodes)
        if (parsed.edges) setEdges(parsed.edges)
        if (parsed.name) setName(parsed.name)
        message.success('已导入工作流 JSON')
      } catch {
        message.error('JSON 解析失败')
      }
    }
    reader.readAsText(file)
  }

  const selectElement = useCallback((els: any) => {
    if (els.length === 1 && els[0].type === 'node') {
      setSelected(nodes.find((n) => n.id === els[0].id) || null)
    } else {
      setSelected(null)
    }
  }, [nodes])

  const selectedMeta = selected?.data as any

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 120px)' }}>
      <Space style={{ marginBottom: 8 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={onBack}>返回模板库</Button>
        <Input
          style={{ width: 220 }}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="工作流名称"
        />
        <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={saveAsTemplate}>
          保存为我的模板
        </Button>
        <Button onClick={exportJson}>导出 JSON</Button>
        <label style={{ cursor: 'pointer' }}>
          <Button>导入 JSON</Button>
          <input
            type="file"
            accept="application/json"
            style={{ display: 'none' }}
            onChange={(e) => e.target.files?.[0] && importJson(e.target.files[0])}
          />
        </label>
      </Space>

      {errors.length > 0 && (
        <Alert style={{ marginBottom: 8 }} type="error" showIcon message="无法保存" description={errors.join('；')} />
      )}

      <div style={{ display: 'flex', flex: 1, gap: 12, minHeight: 0 }}>
        {/* 左侧节点面板 */}
        <div
          style={{
            width: 200,
            border: '1px solid #f0f0f0',
            borderRadius: 8,
            padding: 8,
            overflow: 'auto',
            background: '#fafafa',
          }}
        >
          <Text strong>节点库</Text>
          <Paragraph type="secondary" style={{ fontSize: 11 }}>拖拽节点到画布</Paragraph>
          <Divider style={{ margin: '8px 0' }} />
          {NODE_PALETTE.map((p) => (
            <div
              key={p.key}
              draggable
              onDragStart={(e) => onDragStart(e, p)}
              style={{
                border: `1px solid ${p.color}55`,
                borderRadius: 6,
                padding: '6px 8px',
                marginBottom: 6,
                cursor: 'grab',
                background: '#fff',
              }}
            >
              <Space size={6}>
                <span style={{ color: p.color }}>{p.icon}</span>
                <Text strong style={{ fontSize: 12 }}>{p.label}</Text>
              </Space>
              <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 2 }}>{p.desc}</div>
            </div>
          ))}
        </div>

        {/* 画布 */}
        <div ref={reactFlowWrapper} style={{ flex: 1, border: '1px solid #f0f0f0', borderRadius: 8 }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onSelectionChange={selectElement}
            onDrop={onDrop}
            onDragOver={onDragOver}
            fitView
          >
            <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
            <Controls />
            <MiniMap pannable zoomable />
          </ReactFlow>
        </div>

        {/* 右侧属性面板 */}
        <div style={{ width: 280, border: '1px solid #f0f0f0', borderRadius: 8, padding: 12, overflow: 'auto', background: '#fafafa' }}>
          {!selectedMeta ? (
            <Empty description="选中一个节点编辑属性" style={{ marginTop: 40 }} />
          ) : (
            <Inspector
              data={selectedMeta}
              onChange={updateSelected}
              onArg={updateArg}
              onCondition={updateCondition}
            />
          )}
        </div>
      </div>
    </div>
  )
}

function Inspector({
  data,
  onChange,
  onArg,
  onCondition,
}: {
  data: any
  onChange: (patch: Partial<any>) => void
  onArg: (name: string, value: any) => void
  onCondition: (patch: Partial<{ variable: string; operator: string; value: any }>) => void
}) {
  const typeLabel: Record<string, string> = { tool: '工具', condition: '条件判断', confirm: '人工确认', end: '结束' }
  return (
    <div>
      <Space>
        <Tag color={NODE_COLOR[data.nodeType]}>{typeLabel[data.nodeType] || data.nodeType}</Tag>
        <Text strong>{data.label}</Text>
      </Space>
      <Divider style={{ margin: '10px 0' }} />

      <Text type="secondary">说明</Text>
      <Input.TextArea
        value={data.description || ''}
        onChange={(e) => onChange({ description: e.target.value })}
        placeholder="节点说明"
        rows={2}
        style={{ marginTop: 4 }}
      />

      {data.nodeType === 'tool' && (() => {
        const defs = TOOL_ARGS_DEF[data.tool] || []
        return (
          <>
            <Divider style={{ margin: '10px 0' }} />
            <Text type="secondary">参数</Text>
            {defs.length === 0 && <Paragraph type="secondary" style={{ fontSize: 11 }}>该工具无需额外参数</Paragraph>}
            {defs.map((d) => (
              <div key={d.name} style={{ marginTop: 8 }}>
                <Text style={{ fontSize: 12 }}>{d.label}</Text>
                {d.type === 'number' && (
                  <InputNumber
                    style={{ width: '100%', marginTop: 2 }}
                    value={data.args?.[d.name]}
                    onChange={(v) => onArg(d.name, v)}
                    placeholder={d.name}
                  />
                )}
                {d.type === 'select' && (
                  <Select
                    style={{ width: '100%', marginTop: 2 }}
                    value={data.args?.[d.name] ?? ''}
                    onChange={(v) => onArg(d.name, v)}
                    options={d.options}
                    placeholder="请选择"
                    allowClear
                  />
                )}
                {d.type === 'textarea' && (
                  <Input.TextArea
                    style={{ marginTop: 2 }}
                    value={data.args?.[d.name] ?? ''}
                    onChange={(e) => onArg(d.name, e.target.value)}
                    rows={2}
                    placeholder={d.name}
                  />
                )}
                {d.type === 'text' && (
                  <Input
                    style={{ marginTop: 2 }}
                    value={data.args?.[d.name] ?? ''}
                    onChange={(e) => onArg(d.name, e.target.value)}
                    placeholder={d.name}
                  />
                )}
              </div>
            ))}
          </>
        )
      })()}

      {data.nodeType === 'condition' && (
        <>
          <Divider style={{ margin: '10px 0' }} />
          <Text type="secondary">条件</Text>
          <div style={{ marginTop: 8 }}>
            <Text style={{ fontSize: 12 }}>变量</Text>
            <Input
              style={{ marginTop: 2 }}
              value={data.condition?.variable || ''}
              onChange={(e) => onCondition({ variable: e.target.value })}
              placeholder="如 $results.n1"
            />
          </div>
          <div style={{ marginTop: 8 }}>
            <Text style={{ fontSize: 12 }}>运算符</Text>
            <Select
              style={{ width: '100%', marginTop: 2 }}
              value={data.condition?.operator || 'exists'}
              onChange={(v) => onCondition({ operator: v })}
              options={[
                { label: '存在/非空', value: 'exists' },
                { label: '等于', value: 'eq' },
                { label: '不等于', value: 'ne' },
                { label: '包含', value: 'contains' },
              ]}
            />
          </div>
          <div style={{ marginTop: 8 }}>
            <Text style={{ fontSize: 12 }}>比较值</Text>
            <Input
              style={{ marginTop: 2 }}
              value={data.condition?.value ?? ''}
              onChange={(e) => onCondition({ value: e.target.value })}
              placeholder="可选"
            />
          </div>
        </>
      )}

      {data.nodeType === 'confirm' && (
        <>
          <Divider style={{ margin: '10px 0' }} />
          <Text type="secondary">人工确认关卡</Text>
          <div style={{ marginTop: 8 }}>
            <Text style={{ fontSize: 12 }}>关卡名称</Text>
            <Input
              style={{ marginTop: 2 }}
              value={data.stage || ''}
              onChange={(e) => onChange({ stage: e.target.value, summary: e.target.value || '人工确认关卡' })}
              placeholder="如：研究选题确认"
            />
          </div>
          <div style={{ marginTop: 8 }}>
            <Text style={{ fontSize: 12 }}>引导文案</Text>
            <Input.TextArea
              style={{ marginTop: 2 }}
              value={data.guide || ''}
              onChange={(e) => onChange({ guide: e.target.value })}
              rows={3}
              placeholder="展示给用户的引导说明"
            />
          </div>
        </>
      )}
    </div>
  )
}