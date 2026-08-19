import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Panel,
  useNodesState,
  useEdgesState,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
  type OnSelectionChangeParams,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  Alert,
  Button,
  Drawer,
  Empty,
  message,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  ReloadOutlined,
  ThunderboltOutlined,
  ClearOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import { graphApi, type SmartGraph, type AnalyzeSource } from '../api/graph'
import { getErrorMessage } from '../api/client'
import { formatMarkdownContent } from '../utils/format'

const DIMENSION_LABELS: Record<string, string> = {
  title_keywords: '关键词',
  background: '背景',
  method: '方法',
  results: '结果',
  conclusion: '结论',
  contributions: '创新点',
}

// 片段节点的自定义数据（cluster 颜色 / 摘要 / 出处）
// 索引签名：@xyflow/react v12 要求 Node.data 满足 Record<string, unknown>
interface ChunkData {
  cluster: number
  color: string
  snippet: string
  paperTitle: string
  paperId: string
  page: number | null
  dimension: string
  dimmed: boolean
  [key: string]: unknown
}
type ChunkNodeType = Node<ChunkData, 'chunk'>

/** 片段节点：左侧簇色条 + 两行摘要 + 出处（文献 · 页码 · 维度） */
function ChunkNode({ data, selected }: NodeProps<ChunkNodeType>) {
  return (
    <div
      style={{
        width: 176,
        borderRadius: 6,
        background: '#fff',
        border: `1px solid ${selected ? data.color : '#dcdcdc'}`,
        borderLeft: `4px solid ${data.color}`,
        boxShadow: selected ? `0 0 0 2px ${data.color}55` : '0 1px 2px rgba(0,0,0,0.06)',
        opacity: data.dimmed ? 0.15 : 1,
        cursor: 'pointer',
      }}
    >
      <div
        style={{
          padding: '6px 8px 2px',
          fontSize: 11,
          lineHeight: '15px',
          height: 36,
          overflow: 'hidden',
          color: '#333',
        }}
      >
        {data.snippet || '（无内容）'}
      </div>
      <div style={{ padding: '0 8px 6px', display: 'flex', alignItems: 'center', gap: 4 }}>
        <span
          style={{
            fontSize: 10,
            color: '#888',
            flex: 1,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {data.paperTitle}
          {data.page != null ? ` · p${data.page}` : ''}
        </span>
        <span style={{ fontSize: 10, color: data.color, whiteSpace: 'nowrap' }}>
          {DIMENSION_LABELS[data.dimension] || data.dimension}
        </span>
      </div>
    </div>
  )
}

const nodeTypes: NodeTypes = { chunk: ChunkNode }

export default function SmartGraphPage() {
  const navigate = useNavigate()
  const [graph, setGraph] = useState<SmartGraph | null>(null)
  const [loading, setLoading] = useState(true)
  // 图谱数据整体替换时递增，作为 ReactFlow 的 key 触发重挂载并重新 fitView
  const [reloadSeq, setReloadSeq] = useState(0)
  const [focusCluster, setFocusCluster] = useState<number | null>(null)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [analyzing, setAnalyzing] = useState(false)
  const [analysis, setAnalysis] = useState<{ open: boolean; content: string; sources: AnalyzeSource[] }>({
    open: false,
    content: '',
    sources: [],
  })

  const [nodes, setNodes, onNodesChange] = useNodesState<ChunkNodeType>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])

  const load = useCallback(() => {
    setLoading(true)
    graphApi
      .smart()
      .then((g) => {
        setGraph(g)
        setFocusCluster(null)
        setSelectedIds([])
        setReloadSeq((s) => s + 1)
      })
      .catch((err) => message.error(getErrorMessage(err)))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // 图谱数据 / 图例聚焦变化 → 重建节点与边（聚焦时其余簇淡出、跨簇边隐藏）
  useEffect(() => {
    if (!graph) return
    const clusterMap = new Map(graph.clusters.map((c) => [c.id, c]))
    setNodes(
      graph.nodes.map((nd) => ({
        id: nd.id,
        type: 'chunk' as const,
        position: { x: nd.x, y: nd.y },
        data: {
          cluster: nd.cluster,
          color: clusterMap.get(nd.cluster)?.color || '#5B8FF9',
          snippet: nd.snippet,
          paperTitle: nd.paper_title,
          paperId: nd.paper_id,
          page: nd.page_number,
          dimension: nd.dimension,
          dimmed: focusCluster != null && nd.cluster !== focusCluster,
        },
      })),
    )
    const clusterOf = new Map(graph.nodes.map((nd) => [nd.id, nd.cluster]))
    setEdges(
      graph.edges
        .filter(
          (e) =>
            focusCluster == null ||
            (clusterOf.get(e.source) === focusCluster && clusterOf.get(e.target) === focusCluster),
        )
        .map((e) => ({
          id: `${e.source}->${e.target}`,
          source: e.source,
          target: e.target,
          style: {
            stroke: '#bfbfbf',
            strokeWidth: Math.max(1, Math.round(e.sim * 2.5)),
            opacity: 0.45,
          },
        })),
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, focusCluster])

  // 框选/点选变化（React Flow 内建选择）
  const handleSelectionChange = useCallback(
    ({ nodes: sel }: OnSelectionChangeParams<ChunkNodeType>) => {
      setSelectedIds(sel.map((n) => n.id))
    },
    [],
  )

  const clearSelection = () => {
    setNodes((nds) => nds.map((n) => ({ ...n, selected: false })))
    setSelectedIds([])
  }

  // 双击片段 → 跳转阅读器对应页
  const handleNodeDoubleClick = useCallback(
    (_e: React.MouseEvent, node: ChunkNodeType) => {
      const d = node.data
      navigate(`/reader/${d.paperId}?page=${d.page ?? 1}`)
    },
    [navigate],
  )

  // 框选批量分析（SSE 流式）
  const runAnalyze = () => {
    if (!selectedIds.length) {
      message.warning('请先在图谱中框选片段（按住鼠标左键拖拽）')
      return
    }
    if (analyzing) return
    setAnalyzing(true)
    setAnalysis({ open: true, content: '', sources: [] })
    graphApi
      .analyzeStream(
        selectedIds,
        '',
        (delta) => setAnalysis((a) => ({ ...a, content: a.content + delta })),
        (sources) => setAnalysis((a) => ({ ...a, sources })),
      )
      .catch((err) => message.error(getErrorMessage(err)))
      .finally(() => setAnalyzing(false))
  }

  const focusedClusterInfo = useMemo(
    () => graph?.clusters.find((c) => c.id === focusCluster) ?? null,
    [graph, focusCluster],
  )

  if (loading && !graph) {
    return (
      <div style={{ textAlign: 'center', padding: 100 }}>
        <Spin tip="正在构建语义图谱…" size="large" />
      </div>
    )
  }

  if (graph && graph.node_count === 0) {
    return (
      <div style={{ textAlign: 'center', padding: 100 }}>
        <Empty description="还没有可分析的文献片段">
          <Button type="primary" onClick={() => navigate('/library')}>
            去文献库上传 PDF
          </Button>
        </Empty>
      </div>
    )
  }

  return (
    <div>
      {/* 顶部说明与图例（点击簇聚焦，其余淡出） */}
      <Space direction="vertical" size={8} style={{ width: '100%', marginBottom: 12 }}>
        <Space size={12} wrap align="center">
          <Typography.Title level={5} style={{ margin: 0 }}>
            Smart Graph 语义图谱
          </Typography.Title>
          {graph && (
            <Typography.Text type="secondary">
              {graph.node_count} 个片段 · {graph.clusters.length} 个语义簇
              {graph.total_chunks > graph.node_count
                ? `（文库共 ${graph.total_chunks} 片段，已按文献均衡采样）`
                : ''}
            </Typography.Text>
          )}
          <Button size="small" icon={<ReloadOutlined />} onClick={load} loading={loading}>
            重新构建
          </Button>
        </Space>
        {graph?.mode === 'keyword' && (
          <Alert
            type="info"
            showIcon
            message="当前为离线关键词模式：未配置 Embedding API，图谱基于词袋相似度构建。在「设置」中配置后语义聚类更精准。"
          />
        )}
        {graph && (
          <Space size={[6, 6]} wrap>
            {graph.clusters.map((c) => {
              const active = focusCluster === c.id
              return (
                <Tooltip key={c.id} title={`${c.count} 个片段 · 来自 ${c.papers} 篇文献`}>
                  <Tag.CheckableTag
                    checked={active}
                    onChange={() => setFocusCluster(active ? null : c.id)}
                    style={{
                      border: `1px solid ${c.color}`,
                      background: active ? `${c.color}22` : undefined,
                      color: active ? c.color : '#555',
                      fontWeight: active ? 600 : 400,
                    }}
                  >
                    <span
                      style={{
                        display: 'inline-block',
                        width: 8,
                        height: 8,
                        borderRadius: 4,
                        background: c.color,
                        marginRight: 6,
                      }}
                    />
                    {c.label || `簇 ${c.id + 1}`}（{c.count}）
                  </Tag.CheckableTag>
                </Tooltip>
              )
            })}
          </Space>
        )}
      </Space>

      {/* 图谱画布：拖拽框选片段，双击跳转阅读器 */}
      <div
        style={{
          height: 'calc(100vh - 250px)',
          minHeight: 480,
          border: '1px solid #f0f0f0',
          borderRadius: 8,
          overflow: 'hidden',
        }}
      >
        <ReactFlow<ChunkNodeType>
          key={reloadSeq}
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          onSelectionChange={handleSelectionChange}
          onNodeDoubleClick={handleNodeDoubleClick}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          selectionOnDrag
          panOnDrag={false}
          panOnScroll
          minZoom={0.15}
          maxZoom={2.5}
          fitView
          fitViewOptions={{ padding: 0.12, maxZoom: 1.1 }}
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#e8e8e8" />
          <Controls showInteractive={false} />
          <MiniMap
            pannable
            zoomable
            nodeColor={(n) => (n.data as unknown as ChunkData).color || '#ccc'}
            nodeStrokeWidth={2}
            style={{ width: 160, height: 110 }}
          />
          {/* 聚焦提示 */}
          {focusedClusterInfo && (
            <Panel position="top-right">
              <div
                style={{
                  background: '#fff',
                  border: `1px solid ${focusedClusterInfo.color}`,
                  borderRadius: 6,
                  padding: '4px 10px',
                  fontSize: 12,
                  color: focusedClusterInfo.color,
                  fontWeight: 600,
                }}
              >
                聚焦：{focusedClusterInfo.label}（{focusedClusterInfo.count} 片段）
                <a style={{ marginLeft: 10, fontWeight: 400 }} onClick={() => setFocusCluster(null)}>
                  取消
                </a>
              </div>
            </Panel>
          )}
          {/* 框选工具条 */}
          <Panel position="bottom-center">
            <div
              style={{
                background: '#fff',
                borderRadius: 8,
                boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
                padding: '8px 14px',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
              }}
            >
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {selectedIds.length
                  ? `已选 ${selectedIds.length} 个片段（最多可分析 30 个）`
                  : '按住鼠标左键拖拽框选片段；双击片段跳转阅读器'}
              </Typography.Text>
              <Button
                size="small"
                type="primary"
                icon={<ThunderboltOutlined />}
                onClick={runAnalyze}
                loading={analyzing}
                disabled={!selectedIds.length}
              >
                批量分析
              </Button>
              <Button
                size="small"
                icon={<ClearOutlined />}
                onClick={clearSelection}
                disabled={!selectedIds.length}
              >
                清除选择
              </Button>
            </div>
          </Panel>
        </ReactFlow>
      </div>

      {/* 批量分析结果抽屉（流式渲染 + 引用来源点击跳转） */}
      <Drawer
        title={`批量分析（${selectedIds.length} 个片段）`}
        width={560}
        open={analysis.open}
        onClose={() => setAnalysis((a) => ({ ...a, open: false }))}
        styles={{ body: { paddingTop: 12 } }}
      >
        {analysis.content ? (
          <div className="markdown-body">
            <ReactMarkdown>{formatMarkdownContent(analysis.content)}</ReactMarkdown>
          </div>
        ) : (
          <div style={{ textAlign: 'center', padding: 60 }}>
            <Spin tip="AI 正在综合分析选中的片段…" />
          </div>
        )}
        {analysis.sources.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <Typography.Title level={5}>引用来源（{analysis.sources.length}）</Typography.Title>
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              {analysis.sources.map((s) => (
                <div
                  key={s.index}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    fontSize: 12,
                    padding: '4px 8px',
                    background: '#f6f8fa',
                    borderRadius: 6,
                    cursor: 'pointer',
                  }}
                  onClick={() => navigate(`/reader/${s.paper_id}?page=${s.page ?? 1}`)}
                >
                  <Tag color="blue" style={{ marginInlineEnd: 0 }}>
                    S{s.index}
                  </Tag>
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.paper_title}
                  </span>
                  {s.page != null && <span style={{ color: '#888' }}>第 {s.page} 页</span>}
                  <FileTextOutlined style={{ color: '#888' }} />
                </div>
              ))}
            </Space>
          </div>
        )}
      </Drawer>
    </div>
  )
}
