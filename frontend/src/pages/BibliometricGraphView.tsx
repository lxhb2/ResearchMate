import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Panel,
  useNodesState,
  useEdgesState,
  MarkerType,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from '@xyflow/react'
import {
  Alert,
  Button,
  Drawer,
  Input,
  InputNumber,
  message,
  Segmented,
  Select,
  Slider,
  Space,
  Spin,
  Switch,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import { graphApi, type BibliometricGraph, type BibliometricNode } from '../api/graph'
import { getErrorMessage } from '../api/client'

type ModuleMode = 'semantic' | 'bibliometric'
type ViewMode = 'network' | 'overlay' | 'density'
type OverlayMetric = 'citation' | 'year'

interface BiblioData {
  color: string
  label: string
  value: number
  size: number
  dimmed: boolean
  metric: string
  [key: string]: unknown
}

type BiblioNodeType = Node<BiblioData, 'biblio'>

const NETWORK_OPTIONS = [
  { value: 'co_authorship', label: '合著网络' },
  { value: 'co_occurrence', label: '关键词共现' },
  { value: 'citation', label: '引文网络' },
  { value: 'bibliographic_coupling', label: '文献耦合' },
  { value: 'paper_similarity', label: '论文关联' },
]

const EXTERNAL_OPTIONS = [
  { value: 'openalex', label: 'OpenAlex' },
  { value: 'crossref', label: 'Crossref' },
  { value: 'europe_pmc', label: 'Europe PMC' },
]

function BiblioNode({ data, selected }: NodeProps<BiblioNodeType>) {
  return (
    <div style={{ width: data.size, textAlign: 'center', opacity: data.dimmed ? 0.15 : 1 }}>
      <div
        style={{
          width: data.size,
          height: data.size,
          borderRadius: '50%',
          background: data.color,
          opacity: 0.86,
          border: selected ? '2px solid #111' : '1px solid rgba(0,0,0,.12)',
          boxShadow: selected ? `0 0 0 3px ${data.color}55` : '0 1px 3px rgba(0,0,0,.14)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#fff',
          fontWeight: 700,
          fontSize: Math.max(9, data.size / 4),
        }}
      >
        {data.value}
      </div>
      <div
        style={{
          marginTop: 3,
          width: 118,
          marginLeft: (data.size - 118) / 2,
          fontSize: 10,
          lineHeight: '13px',
          color: '#333',
          overflow: 'hidden',
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical',
        }}
      >
        {data.label}
      </div>
    </div>
  )
}

const nodeTypes: NodeTypes = { biblio: BiblioNode }

function metricColor(ratio: number) {
  const hue = 212 - 172 * Math.max(0, Math.min(1, ratio))
  return `hsl(${hue}, 76%, ${44 + 12 * ratio}%)`
}

export default function BibliometricGraphView({
  moduleMode,
  onModuleChange,
}: {
  moduleMode: ModuleMode
  onModuleChange: (mode: ModuleMode) => void
}) {
  const [graph, setGraph] = useState<BibliometricGraph | null>(null)
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [reloadSeq, setReloadSeq] = useState(0)
  const [viewMode, setViewMode] = useState<ViewMode>('network')
  const [overlayMetric, setOverlayMetric] = useState<OverlayMetric>('citation')
  const [focusCluster, setFocusCluster] = useState<number | null>(null)
  const [showEdges, setShowEdges] = useState(true)
  const [minWeight, setMinWeight] = useState(1)
  const [networkType, setNetworkType] = useState<BibliometricGraph['network_type']>('co_authorship')
  const [sourceType, setSourceType] = useState<'library' | 'external'>('library')
  const [externalSource, setExternalSource] = useState('openalex')
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(50)
  const [clusterResolution, setClusterResolution] = useState(1)
  const [selectedNode, setSelectedNode] = useState<BibliometricNode | null>(null)

  const [nodes, setNodes, onNodesChange] = useNodesState<BiblioNodeType>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])

  const resolutionRef = useRef(clusterResolution)
  resolutionRef.current = clusterResolution

  const load = useCallback((nextResolution?: number) => {
    if (sourceType === 'external' && !query.trim()) {
      message.warning('请输入外部检索主题')
      return
    }
    setLoading(true)
    graphApi
      .bibliometric({
        network_type: networkType,
        source: sourceType,
        query: query.trim(),
        external_source: externalSource,
        limit,
        cluster_resolution: nextResolution ?? resolutionRef.current,
      })
      .then((data) => {
        setGraph(data)
        setFocusCluster(null)
        setSelectedNode(null)
        setMinWeight(1)
        setReloadSeq((value) => value + 1)
      })
      .catch((error) => message.error(getErrorMessage(error)))
      .finally(() => setLoading(false))
  }, [externalSource, limit, networkType, query, sourceType])

  const exportVOSviewer = useCallback(async () => {
    if (sourceType === 'external' && !query.trim()) {
      message.warning('请输入外部检索主题')
      return
    }
    setExporting(true)
    try {
      const blob = await graphApi.exportVOSviewer({
        network_type: networkType,
        source: sourceType,
        query: query.trim(),
        external_source: externalSource,
        limit,
        cluster_resolution: clusterResolution,
      })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `researchmate-${networkType.replace(/_/g, '-')}-vosviewer.zip`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      message.success('已导出 VOSviewer 地图与网络文件')
    } catch (error) {
      message.error(getErrorMessage(error))
    } finally {
      setExporting(false)
    }
  }, [clusterResolution, externalSource, limit, networkType, query, sourceType])

  useEffect(() => {
    load()
  }, [load])

  const metricRange = useMemo(() => {
    if (!graph) return { min: 0, max: 0 }
    const values = graph.nodes
      .map((node) => (overlayMetric === 'year' ? Number(node.extra.year || 0) : node.extra.citation_count || 0))
      .filter((value) => value > 0)
    return values.length
      ? { min: Math.min(...values), max: Math.max(...values) }
      : { min: 0, max: 0 }
  }, [graph, overlayMetric])

  useEffect(() => {
    if (!graph) return
    const values = graph.nodes.map((node) => Math.max(1, node.value))
    const minValue = Math.min(...values)
    const maxValue = Math.max(...values)
    const clusterMap = new Map(graph.clusters.map((cluster) => [cluster.id, cluster]))
    const degreeMap = new Map<string, number>()
    for (const edge of graph.edges) {
      degreeMap.set(edge.source, (degreeMap.get(edge.source) || 0) + edge.weight)
      degreeMap.set(edge.target, (degreeMap.get(edge.target) || 0) + edge.weight)
    }
    const maxDensity = Math.max(
      1,
      ...graph.nodes.map((node) => (degreeMap.get(node.id) || 0) + node.value),
    )

    setNodes(
      graph.nodes.map((node) => {
        const ratio = maxValue === minValue ? 0.55 : (node.value - minValue) / (maxValue - minValue)
        const baseSize = 32 + 40 * Math.sqrt(ratio)
        let color = clusterMap.get(node.cluster)?.color || '#5B8FF9'
        let metric = `${node.value}`
        if (viewMode === 'overlay') {
          const raw = overlayMetric === 'year' ? Number(node.extra.year || 0) : node.extra.citation_count || 0
          const rawRatio = metricRange.max === metricRange.min ? 0.5 : (raw - metricRange.min) / (metricRange.max - metricRange.min)
          color = metricColor(rawRatio)
          metric = raw ? `${raw}` : '—'
        } else if (viewMode === 'density') {
          const intensity = ((degreeMap.get(node.id) || 0) + node.value) / maxDensity
          color = metricColor(intensity)
          metric = `强度 ${(intensity * 100).toFixed(0)}%`
        }
        return {
          id: node.id,
          type: 'biblio' as const,
          position: { x: node.x, y: node.y },
          data: {
            color,
            label: node.label,
            value: node.value,
            size: viewMode === 'density' ? baseSize * 1.1 : baseSize,
            dimmed: focusCluster != null && node.cluster !== focusCluster,
            metric,
          },
        }
      }),
    )

    const weights = graph.edges.map((edge) => edge.weight)
    const maxWeight = Math.max(1, ...weights)
    setEdges(
      showEdges
        ? graph.edges
            .filter((edge) => edge.weight >= minWeight)
            .map((edge) => {
              const ratio = (edge.weight - 1) / Math.max(1, maxWeight - 1)
        return {
          id: `${edge.source}->${edge.target}`,
                source: edge.source,
                target: edge.target,
                animated: false,
                markerEnd: graph.directed ? { type: MarkerType.ArrowClosed, width: 15, height: 15 } : undefined,
                style: {
                  stroke: graph.network_type === 'paper_similarity' && edge.kinds?.includes('citation')
                    ? (focusCluster == null ? '#4a7ad9' : '#8fb0e4')
                    : (focusCluster == null ? '#8496ad' : '#a9c0dc'),
                  strokeWidth: 1 + ratio * 4,
                  strokeDasharray: graph.network_type === 'paper_similarity' && !edge.kinds?.includes('citation') ? '5 4' : undefined,
                  opacity: focusCluster == null ? 0.24 + ratio * 0.5 : 0.12,
                },
              }
            })
        : [],
    )
  }, [graph, focusCluster, minWeight, showEdges, viewMode, overlayMetric, metricRange])

  const focusedCluster = graph?.clusters.find((cluster) => cluster.id === focusCluster) || null

  return (
    <div>
      <Space direction="vertical" size={8} style={{ width: '100%', marginBottom: 12 }}>
        <Space size={12} wrap align="center">
          <Typography.Title level={5} style={{ margin: 0 }}>
            文献计量图谱
          </Typography.Title>
          <Segmented
            size="small"
            value={moduleMode}
            onChange={(value) => onModuleChange(value as ModuleMode)}
            options={[
              { label: '语义图谱', value: 'semantic' },
              { label: '文献计量图谱', value: 'bibliometric' },
            ]}
          />
          <Select
            size="small"
            style={{ minWidth: 132 }}
            value={networkType}
            onChange={(value) => setNetworkType(value)}
            options={NETWORK_OPTIONS}
          />
          <Segmented
            size="small"
            value={sourceType}
            onChange={(value) => setSourceType(value as 'library' | 'external')}
            options={[
              { label: '文献库', value: 'library' },
              { label: '外部检索', value: 'external' },
            ]}
          />
          <Button size="small" icon={<ReloadOutlined />} onClick={() => load()} loading={loading}>
            构建图谱
          </Button>
          <Button
            size="small"
            icon={<DownloadOutlined />}
            onClick={exportVOSviewer}
            loading={exporting}
            disabled={!graph || graph.node_count === 0}
          >
            VOSviewer
          </Button>
        </Space>

        <Space size={8} wrap align="center">
          {sourceType === 'external' && (
            <>
              <Select
                size="small"
                style={{ minWidth: 128 }}
                value={externalSource}
                onChange={setExternalSource}
                options={EXTERNAL_OPTIONS}
              />
              <Input
                size="small"
                style={{ width: 260 }}
                placeholder="输入研究主题，如 transformer"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onPressEnter={() => load()}
              />
            </>
          )}
          <Tooltip title="最多纳入分析的论文数量">
            <InputNumber size="small" min={10} max={100} value={limit} onChange={(value) => setLimit(value || 50)} />
          </Tooltip>
          <Tooltip title="调大得到更细的聚类，调小得到更粗的聚类">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                分辨率
              </Typography.Text>
              <Slider
                min={0.25}
                max={2}
                step={0.05}
                value={clusterResolution}
                onChange={(value) => setClusterResolution(value)}
                onChangeComplete={(value) => load(Number(value))}
                style={{ width: 132, marginBottom: 0 }}
              />
            </div>
          </Tooltip>
          <Segmented
            size="small"
            value={viewMode}
            onChange={(value) => setViewMode(value as ViewMode)}
            options={[
              { label: '网络视图', value: 'network' },
              { label: '叠加视图', value: 'overlay' },
              { label: '密度视图', value: 'density' },
            ]}
          />
          {viewMode === 'overlay' && (
            <Segmented
              size="small"
              value={overlayMetric}
              onChange={(value) => setOverlayMetric(value as OverlayMetric)}
              options={[
                { label: '被引', value: 'citation' },
                { label: '年份', value: 'year' },
              ]}
            />
          )}
          {graph && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {graph.paper_count} 篇论文 · {graph.node_count} 节点 · {graph.edge_count} 连线 · 分辨率 {graph.cluster_resolution.toFixed(2)}
            </Typography.Text>
          )}
        </Space>

        {sourceType === 'library' && ['citation', 'bibliographic_coupling', 'paper_similarity'].includes(networkType) && (
          <Alert
            type="info"
            showIcon
            message={networkType === 'paper_similarity'
              ? '论文关联网络按标题、关键词和摘要计算相似论文，并按 DOI 合并 OpenAlex 引用连线。'
              : '引文与耦合网络会按 DOI 通过 OpenAlex 批量补全参考文献；无 DOI 的论文不会参与引用连线。'}
          />
        )}
        {graph?.enrichment_source && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            已使用 {graph.enrichment_source} 补全引用元数据
          </Typography.Text>
        )}
        {graph && graph.clusters.length > 0 && (
          <Space size={[6, 6]} wrap>
            {graph.clusters.map((cluster) => {
              const active = focusCluster === cluster.id
              return (
                <Tooltip key={cluster.id} title={`${cluster.count} 个节点`}>
                  <Tag.CheckableTag
                    checked={active}
                    onChange={() => setFocusCluster(active ? null : cluster.id)}
                    style={{
                      border: `1px solid ${cluster.color}`,
                      background: active ? `${cluster.color}22` : undefined,
                      color: active ? cluster.color : '#555',
                      fontWeight: active ? 600 : 400,
                    }}
                  >
                    <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 4, background: cluster.color, marginRight: 6 }} />
                    {cluster.label}（{cluster.count}）
                  </Tag.CheckableTag>
                </Tooltip>
              )
            })}
          </Space>
        )}
        {graph && (
          <Space size={[8, 8]} wrap align="center">
            <Switch size="small" checked={showEdges} onChange={setShowEdges} />
            <Typography.Text style={{ fontSize: 12 }}>关系连线</Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              权重 ≥
            </Typography.Text>
            <Slider min={1} max={Math.max(1, graph.edges[0]?.weight || 1)} value={minWeight} onChange={setMinWeight} style={{ width: 140 }} />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {viewMode === 'network' ? '颜色=聚类' : viewMode === 'overlay' ? '颜色=叠加指标' : '颜色=局部密度'}
              · 大小=权重
            </Typography.Text>
          </Space>
        )}
      </Space>

      <div style={{ height: 'calc(100vh - 280px)', minHeight: 480, border: '1px solid #f0f0f0', borderRadius: 8, overflow: 'hidden' }}>
        {loading && !graph ? (
          <div style={{ display: 'grid', placeItems: 'center', height: '100%' }}>
            <Spin tip="正在构建文献计量图谱…" size="large" />
          </div>
        ) : !graph || graph.node_count === 0 ? (
          <div style={{ display: 'grid', placeItems: 'center', height: '100%' }}>
            <Typography.Text type="secondary">
              {sourceType === 'library' ? '文献库中没有可构建网络的数据' : '外部检索没有返回可构建网络的数据'}
            </Typography.Text>
          </div>
        ) : (
          <ReactFlow<BiblioNodeType>
            key={`${reloadSeq}-${viewMode}`}
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={nodeTypes}
            onNodeClick={(_, node) => setSelectedNode(graph.nodes.find((item) => item.id === node.id) || null)}
            nodesConnectable={false}
            selectionOnDrag
            panOnDrag={false}
            panOnScroll
            minZoom={0.12}
            maxZoom={2.5}
            fitView
            fitViewOptions={{ padding: 0.14, maxZoom: 1.05 }}
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#e8e8e8" />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable nodeColor={(node) => (node.data as BiblioData).color || '#ccc'} style={{ width: 150, height: 104 }} />
            {focusedCluster && (
              <Panel position="top-right">
                <div style={{ background: '#fff', border: `1px solid ${focusedCluster.color}`, borderRadius: 6, padding: '4px 10px', fontSize: 12, color: focusedCluster.color, fontWeight: 600 }}>
                  聚焦：{focusedCluster.label}
                  <a style={{ marginLeft: 10, fontWeight: 400 }} onClick={() => setFocusCluster(null)}>
                    取消
                  </a>
                </div>
              </Panel>
            )}
            <Panel position="bottom-center">
              <div style={{ background: '#fff', borderRadius: 8, boxShadow: '0 2px 8px rgba(0,0,0,.14)', padding: '7px 12px', fontSize: 12, color: '#666' }}>
                点击节点查看详情；拖动空白处平移，滚轮缩放
              </div>
            </Panel>
          </ReactFlow>
        )}
      </div>

      <Drawer
        title="节点详情"
        width={420}
        open={!!selectedNode}
        onClose={() => setSelectedNode(null)}
      >
        {selectedNode ? (
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            <Typography.Title level={5} style={{ marginBottom: 0 }}>
              {selectedNode.label}
            </Typography.Title>
            <Space size={6} wrap>
              <Tag color="blue">权重 {selectedNode.value}</Tag>
              {selectedNode.extra.year ? <Tag>年份 {selectedNode.extra.year}</Tag> : null}
              {selectedNode.extra.citation_count != null ? <Tag>被引 {selectedNode.extra.citation_count}</Tag> : null}
              {selectedNode.extra.papers ? <Tag>关联论文 {selectedNode.extra.papers}</Tag> : null}
              {selectedNode.extra.reference_count ? <Tag>参考文献 {selectedNode.extra.reference_count}</Tag> : null}
            </Space>
            {selectedNode.extra.authors && selectedNode.extra.authors.length > 0 && (
              <Typography.Paragraph>
                <Typography.Text strong>作者：</Typography.Text>
                {selectedNode.extra.authors.join(', ')}
              </Typography.Paragraph>
            )}
            {selectedNode.extra.doi && (
              <Typography.Paragraph copyable={{ text: selectedNode.extra.doi }}>
                <Typography.Text strong>DOI：</Typography.Text>
                {selectedNode.extra.doi}
              </Typography.Paragraph>
            )}
            {sourceType === 'library' && selectedNode.extra.paper_id && (
              <Button type="primary" onClick={() => window.location.assign(`/reader/${selectedNode.extra.paper_id}`)}>
                打开阅读器
              </Button>
            )}
          </Space>
        ) : null}
      </Drawer>
    </div>
  )
}
