import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
  type OnNodeDrag,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  Alert,
  Button,
  Drawer,
  Empty,
  message,
  Segmented,
  Slider,
  Space,
  Spin,
  Switch,
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
import BibliometricGraphView from './BibliometricGraphView'

const DIMENSION_LABELS: Record<string, string> = {
  title_keywords: '关键词',
  background: '背景',
  method: '方法',
  results: '结果',
  conclusion: '结论',
  contributions: '创新点',
}
const DIMENSION_ITEMS: [string, string][] = [
  ['title_keywords', '关键词'],
  ['background', '背景'],
  ['method', '方法'],
  ['results', '结果'],
  ['conclusion', '结论'],
  ['contributions', '创新点'],
  ['text', '原文片段'],
]

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
  section: string | null
  dimmed: boolean
  paperCount?: number
  [key: string]: unknown
}
type ChunkNodeType = Node<ChunkData, 'chunk'>

interface LayoutPoint {
  id: string
  x: number
  y: number
}

/** 轻量力导向布局：斥力 + 连线引力 + 向心力，结果稳定可拖拽微调。 */
function runForceLayout(
  points: LayoutPoint[],
  links: { source: string; target: string }[],
  width = 1800,
  height = 1400,
  iterations = 300,
  clusters?: Map<string, number>,
): Record<string, { x: number; y: number }> {
  const pos = new Map(points.map((p) => [p.id, { x: p.x, y: p.y }]))
  const k = 150
  const linkDist = 210
  // 固定簇中心：节点向自己所在语义簇中心聚集，避免力导向后簇被冲散
  const clusterCenters = new Map<number, { x: number; y: number }>()
  if (clusters) {
    const sums = new Map<number, { x: number; y: number; count: number }>()
    for (const p of points) {
      const c = clusters.get(p.id)
      if (c == null) continue
      const s = sums.get(c) || { x: 0, y: 0, count: 0 }
      s.x += p.x
      s.y += p.y
      s.count += 1
      sums.set(c, s)
    }
    for (const [c, s] of sums) {
      clusterCenters.set(c, { x: s.x / s.count, y: s.y / s.count })
    }
  }
  for (let iter = 0; iter < iterations; iter++) {
    const alpha = 0.85 * (1 - iter / iterations)
    const forces = new Map<string, { x: number; y: number }>()
    for (const p of points) forces.set(p.id, { x: 0, y: 0 })
    // 斥力
    for (let i = 0; i < points.length; i++) {
      for (let j = i + 1; j < points.length; j++) {
        const a = pos.get(points[i].id)!
        const b = pos.get(points[j].id)!
        let dx = a.x - b.x
        let dy = a.y - b.y
        let dist = Math.hypot(dx, dy) || 1
        dx /= dist
        dy /= dist
        const rep = (k * k) / Math.max(60, dist * dist)
        const fa = forces.get(points[i].id)!
        const fb = forces.get(points[j].id)!
        fa.x += dx * rep
        fa.y += dy * rep
        fb.x -= dx * rep
        fb.y -= dy * rep
      }
    }
    // 连线引力
    for (const link of links) {
      const a = pos.get(link.source)
      const b = pos.get(link.target)
      if (!a || !b) continue
      let dx = b.x - a.x
      let dy = b.y - a.y
      const dist = Math.hypot(dx, dy) || 1
      dx /= dist
      dy /= dist
      const pull = (dist - linkDist) * 0.08
      const fa = forces.get(link.source)!
      const fb = forces.get(link.target)!
      fa.x += dx * pull
      fa.y += dy * pull
      fb.x -= dx * pull
      fb.y -= dy * pull
    }
    // 向心力
    for (const p of points) {
      const f = forces.get(p.id)!
      const c = pos.get(p.id)!
      f.x += (width / 2 - c.x) * 0.012
      f.y += (height / 2 - c.y) * 0.012
      if (clusters) {
        const cc = clusterCenters.get(clusters.get(p.id)!)
        if (cc) {
          f.x += (cc.x - c.x) * 0.055
          f.y += (cc.y - c.y) * 0.055
        }
      }
    }
    for (const p of points) {
      const c = pos.get(p.id)!
      const f = forces.get(p.id)!
      c.x += f.x * alpha
      c.y += f.y * alpha
    }
  }
  return Object.fromEntries(pos)
}

/** 片段节点：左侧簇色条 + 两行摘要 + 出处（文献 · 页码 · 维度） */
function ChunkNode({ data, selected }: NodeProps<ChunkNodeType>) {
  const isPaper = !!data.paperCount
  return (
    <div
      style={{
        width: isPaper ? 224 : 176,
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
        {isPaper ? data.paperTitle || '未命名' : data.snippet || '（无内容）'}
      </div>
      <div style={{ padding: '0 8px 6px', display: 'flex', alignItems: 'center', gap: 4 }}>
        {isPaper ? (
          <span style={{ fontSize: 10, color: '#888', flex: 1 }}>
            {data.paperCount} 个片段 · 双击进入阅读器
          </span>
        ) : (
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
            {data.section ? ` · ${data.section}` : ''}
          </span>
        )}
        <span style={{ fontSize: 10, color: data.color, whiteSpace: 'nowrap' }}>
          {isPaper ? '论文' : DIMENSION_LABELS[data.dimension] || data.dimension}
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
  const [dimensionFilter, setDimensionFilter] = useState<string | null>(null)
  const [paperView, setPaperView] = useState(false)
  const [moduleMode, setModuleMode] = useState<'semantic' | 'bibliometric'>('semantic')
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [analyzing, setAnalyzing] = useState(false)
  const [showEdges, setShowEdges] = useState(true)
  const [minSim, setMinSim] = useState(0.2)
  const savedPositions = useRef<Record<string, { x: number; y: number }>>({})
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
        savedPositions.current = {}
        setGraph(g)
        setFocusCluster(null)
        setDimensionFilter(null)
        setPaperView(false)
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
    const visibleChunks = graph.nodes.filter(
      (nd) => dimensionFilter == null || nd.dimension === dimensionFilter,
    )
    const clusterOf = new Map(graph.nodes.map((nd) => [nd.id, nd.cluster]))
    const dimensionOf = new Map(graph.nodes.map((nd) => [nd.id, nd.dimension]))

    if (paperView) {
      const byPaper = new Map<
        string,
        { id: string; paperId: string; title: string; nodes: typeof graph.nodes }
      >()
      for (const nd of visibleChunks) {
        const id = `paper:${nd.paper_id}`
        const prev = byPaper.get(id)
        if (prev) {
          prev.nodes.push(nd)
        } else {
          byPaper.set(id, { id, paperId: nd.paper_id, title: nd.paper_title, nodes: [nd] })
        }
      }
      setNodes(
        Array.from(byPaper.values()).map((p) => {
          const cluster = p.nodes[0]?.cluster ?? 0
          const avgX = p.nodes.reduce((s, n) => s + n.x, 0) / p.nodes.length
          const avgY = p.nodes.reduce((s, n) => s + n.y, 0) / p.nodes.length
          return {
            id: p.id,
            type: 'chunk' as const,
            position: savedPositions.current[p.id] || { x: avgX, y: avgY },
            data: {
              cluster,
              color: clusterMap.get(cluster)?.color || '#5B8FF9',
              snippet: p.title,
              paperTitle: p.title,
              paperId: p.paperId,
              page: null,
              dimension: 'paper',
              section: null,
              dimmed: focusCluster != null && cluster !== focusCluster,
              paperCount: p.nodes.length,
            },
          }
        }),
      )
      if (!showEdges) {
        setEdges([])
        return
      }
      const paperPair = new Map<string, { source: string; target: string; sim: number }>()
      for (const e of graph.edges) {
        const a = graph.nodes.find((n) => n.id === e.source)
        const b = graph.nodes.find((n) => n.id === e.target)
        if (!a || !b || a.paper_id === b.paper_id) continue
        const pa = `paper:${a.paper_id}`
        const pb = `paper:${b.paper_id}`
        const key = pa < pb ? `${pa}->${pb}` : `${pb}->${pa}`
        const prev = paperPair.get(key)
        if (!prev || e.sim > prev.sim) {
          paperPair.set(key, { source: pa, target: pb, sim: e.sim })
        }
      }
      setEdges(
        Array.from(paperPair.values())
          .filter((e) => e.sim >= minSim)
          .map((e) => ({
            id: `${e.source}->${e.target}`,
            source: e.source,
            target: e.target,
            label: e.sim >= 0.5 ? `${Math.round(e.sim * 100)}%` : undefined,
            labelStyle: { fontSize: 9, fill: '#6b7280', fontWeight: 600 },
            labelBgStyle: { fill: '#ffffff', fillOpacity: 0.75 },
            labelBgPadding: [2, 2] as [number, number],
            labelBgBorderRadius: 3,
            style: {
              stroke: '#9aa7b8',
              strokeWidth: Math.max(1, Math.round(e.sim * 3)),
              opacity: Math.min(0.9, 0.35 + e.sim * 0.55),
            },
          })),
      )
      return
    }

    setNodes(
      visibleChunks.map((nd) => ({
        id: nd.id,
        type: 'chunk' as const,
        position: savedPositions.current[nd.id] || { x: nd.x, y: nd.y },
        data: {
          cluster: nd.cluster,
          color: clusterMap.get(nd.cluster)?.color || '#5B8FF9',
          snippet: nd.snippet,
          paperTitle: nd.paper_title,
          paperId: nd.paper_id,
          page: nd.page_number,
          dimension: nd.dimension,
          section: nd.section,
          dimmed:
            (focusCluster != null && nd.cluster !== focusCluster) ||
            false,
        },
      })),
    )
    if (!showEdges) {
      setEdges([])
      return
    }
    setEdges(
      graph.edges
        .filter(
          (e) =>
            e.sim >= minSim &&
            (dimensionFilter == null ||
              (dimensionOf.get(e.source) === dimensionFilter && dimensionOf.get(e.target) === dimensionFilter)) &&
            (focusCluster == null ||
              (clusterOf.get(e.source) === focusCluster && clusterOf.get(e.target) === focusCluster)),
        )
        .map((e) => ({
          id: `${e.source}->${e.target}`,
          source: e.source,
          target: e.target,
          label: e.sim >= 0.5 ? `${Math.round(e.sim * 100)}%` : undefined,
          labelStyle: { fontSize: 9, fill: '#6b7280', fontWeight: 600 },
          labelBgStyle: { fill: '#ffffff', fillOpacity: 0.75 },
          labelBgPadding: [2, 2] as [number, number],
          labelBgBorderRadius: 3,
          style: {
            stroke: '#9aa7b8',
            strokeWidth: Math.max(1, Math.round(e.sim * 3)),
            opacity: Math.min(0.9, 0.35 + e.sim * 0.55),
          },
        })),
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, focusCluster, minSim, showEdges, dimensionFilter, paperView])

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

  const handleNodeDragStop = useCallback<OnNodeDrag<ChunkNodeType>>((_e, node) => {
    savedPositions.current[node.id] = { x: node.position.x, y: node.position.y }
  }, [])

  const applyForceLayout = useCallback(() => {
    setNodes((nds) => {
      const pts = nds.map((n) => ({ id: n.id, x: n.position.x, y: n.position.y }))
      const linkIds = new Set(nds.map((n) => n.id))
      const links = edges
        .filter((e) => linkIds.has(e.source) && linkIds.has(e.target))
        .map((e) => ({ source: e.source, target: e.target }))
      const clusters = new Map<string, number>(
        nds.map((n) => [n.id, (n.data as ChunkData).cluster]),
      )
      const next = runForceLayout(pts, links, 1800, 1400, 300, clusters)
      nds.forEach((n) => {
        if (next[n.id]) savedPositions.current[n.id] = next[n.id]
      })
      return nds.map((n) => ({ ...n, position: next[n.id] || n.position }))
    })
  }, [edges, setNodes])

  // 图谱加载后自动执行一次簇感知力导向布局，避免默认位置叠在一起
  useEffect(() => {
    if (!nodes.length || reloadSeq === 0) return
    const t = setTimeout(() => applyForceLayout(), 0)
    return () => clearTimeout(t)
  }, [reloadSeq, applyForceLayout])

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

  const moduleSwitch = (
    <Segmented
      size="small"
      value={moduleMode}
      onChange={(value) => setModuleMode(value as 'semantic' | 'bibliometric')}
      options={[
        { label: '语义图谱', value: 'semantic' },
        { label: '文献计量图谱', value: 'bibliometric' },
      ]}
    />
  )

  if (loading && !graph) {
    return (
      <div style={{ textAlign: 'center', padding: 72 }}>
        {moduleSwitch}
        <div style={{ marginTop: 18 }}>
          <Spin tip="正在构建语义图谱…" size="large" />
        </div>
      </div>
    )
  }

  if (graph && graph.node_count === 0) {
    return (
      <div style={{ textAlign: 'center', padding: 72 }}>
        {moduleSwitch}
        <div style={{ marginTop: 18 }}>
          <Empty description="还没有可分析的文献片段">
            <Button type="primary" onClick={() => navigate('/library')}>
              去文献库上传 PDF
            </Button>
          </Empty>
        </div>
      </div>
    )
  }

  if (moduleMode === 'bibliometric') {
    return <BibliometricGraphView moduleMode={moduleMode} onModuleChange={setModuleMode} />
  }

  return (
    <div>
      {/* 顶部说明与图例（点击簇聚焦，其余淡出） */}
      <Space direction="vertical" size={8} style={{ width: '100%', marginBottom: 12 }}>
        <Space size={12} wrap align="center">
          {moduleSwitch}
          <Typography.Title level={5} style={{ margin: 0 }}>
            Smart Graph 语义图谱
          </Typography.Title>
          <Segmented
            size="small"
            value={paperView ? 'paper' : 'chunk'}
            onChange={(v) => setPaperView(v === 'paper')}
            options={[
              { label: '片段视图', value: 'chunk' },
              { label: '论文视图', value: 'paper' },
            ]}
          />
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
          <Button size="small" onClick={applyForceLayout} disabled={!nodes.length}>
            力导向布局
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
        {graph && (
          <Space size={[6, 6]} wrap>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              按拆分维度聚焦
            </Typography.Text>
            {DIMENSION_ITEMS.map(([key, label]) => {
              const count = graph.nodes.filter((n) => n.dimension === key).length
              if (count === 0) return null
              const active = dimensionFilter === key
              return (
                <Tooltip key={key} title={`${label}维度 ${count} 个片段`}>
                  <Tag.CheckableTag
                    checked={active}
                    onChange={() => setDimensionFilter(active ? null : key)}
                    style={{
                      border: active ? '1px solid #4f46e5' : '1px solid #d9d9d9',
                      background: active ? '#eef2ff' : undefined,
                      color: active ? '#4f46e5' : '#555',
                      fontWeight: active ? 600 : 400,
                    }}
                  >
                    {label}（{count}）
                  </Tag.CheckableTag>
                </Tooltip>
              )
            })}
          </Space>
        )}
        {graph && graph.edges.length > 0 && (
          <Space size={[8, 8]} wrap align="center">
            <Switch size="small" checked={showEdges} onChange={setShowEdges} />
            <Typography.Text style={{ fontSize: 12 }}>近似内容连线</Typography.Text>
            {showEdges && (
              <>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  相似度 ≥
                </Typography.Text>
                <Slider
                  min={0.1}
                  max={0.9}
                  step={0.05}
                  value={minSim}
                  onChange={setMinSim}
                  style={{ width: 160, margin: '0 4px' }}
                  tooltip={{ formatter: (v) => `${Math.round((v ?? 0) * 100)}%` }}
                />
                <Typography.Text type="secondary" style={{ fontSize: 12, minWidth: 36 }}>
                  {Math.round(minSim * 100)}%
                </Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  当前显示 {graph.edges.filter((e) => e.sim >= minSim).length} 条
                </Typography.Text>
              </>
            )}
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
          onNodeDragStop={handleNodeDragStop}
          nodeTypes={nodeTypes}
          onSelectionChange={handleSelectionChange}
          onNodeDoubleClick={handleNodeDoubleClick}
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
                  : '拖动方块调整布局；空白处按住左键框选；双击片段跳转阅读器'}
              </Typography.Text>
              <Button
                size="small"
                type="primary"
                icon={<ThunderboltOutlined />}
                onClick={runAnalyze}
                loading={analyzing}
                disabled={!selectedIds.length || paperView}
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
