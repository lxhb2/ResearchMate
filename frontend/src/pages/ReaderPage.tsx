import { useEffect, useState, useRef, useMemo } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import {
  Row,
  Col,
  Button,
  Tabs,
  Input,
  Spin,
  message,
  Typography,
  List,
  Tag,
  Empty,
  Space,
  Modal,
  Divider,
  Tooltip,
  Dropdown,
  Select,
} from 'antd'
import {
  ArrowLeftOutlined,
  SendOutlined,
  ThunderboltOutlined,
  ExportOutlined,
  GlobalOutlined,
  MoreOutlined,
  ClearOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
  ColumnWidthOutlined,
  PushpinOutlined,
  EditOutlined,
  DeleteOutlined,
  HolderOutlined,
  RedoOutlined,
} from '@ant-design/icons'
import { Document, Page, pdfjs } from 'react-pdf'
import PdfJsWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?worker'
import ReactMarkdown from 'react-markdown'
// react-pdf 文字层/批注层样式：必须导入，否则文字层不会绝对定位铺在 canvas 上，
// 会导致"选中文字与原 PDF 错层"（内容被排成上下两段、无法在原位选中）。
import 'react-pdf/dist/Page/TextLayer.css'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import type { Paper, Annotation, Project } from '../types'
import { papersApi, type PaperAnalysis } from '../api/papers'
import { annotationsApi, translateApi, termApi, type PinCard } from '../api/search'
import { projectsApi } from '../api/projects'
import { api, getErrorMessage } from '../api/client'
import { formatMarkdownContent } from '../utils/format'

// 配置 pdf.js worker：用 Vite 的 ?worker 把 worker 单独打包成独立文件。
// 沙盒环境禁止 module Worker（new Worker(src, {type:'module'})）与动态 import()，
// 因此靠 vite worker.format:'iife' 生成经典脚本 worker，兼容受限环境。
// 直接通过 workerPort 交给 pdf.js，避免主线程 fake worker 在传递数据时
// structuredClone 掉原始 ArrayBuffer，引发 "Cannot perform Construct on a detached ArrayBuffer"。
pdfjs.GlobalWorkerOptions.workerPort = new PdfJsWorker()

// 中文 PDF 多用 Type0 CID 字体（如编码 GBK-EUC-H / UniGB-UCS2-H），
// pdf.js 必须借助 cmaps 目录才能把这些字体的字符码映射成字形。
// 这里把 pdfjs-dist 的 cmaps / standard_fonts 拷贝到 public/pdfjs/ 提供访问，
// 并开启 cMapPacked（.bcmap 打包格式），否则中文字体无法渲染、只有英文正常。
const PDFJS_CMAPS_URL = `${import.meta.env.BASE_URL}pdfjs/cmaps/`
const PDFJS_STANDARD_FONTS_URL = `${import.meta.env.BASE_URL}pdfjs/standard_fonts/`

// 稳定引用的 Document options（模块级常量）。react-pdf 的 loadDocument effect 依赖 options
// 引用，若每次渲染都新建对象，会反复执行 effect 并重复调用 getDocument，导致 pdf.js 把
// 同一个 ArrayBuffer 多次转移/分离，报 "Cannot perform Construct on a detached ArrayBuffer"。
const PDF_OPTIONS = {
  cMapUrl: PDFJS_CMAPS_URL,
  cMapPacked: true,
  standardFontDataUrl: PDFJS_STANDARD_FONTS_URL,
}

const { TextArea } = Input

interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
  /** AI 回答的引用来源（页码 + 片段），点击可跳转 PDF 对应页高亮 */
  citations?: { page: number | null; snippet: string }[]
}

// 6 个快捷提问按钮（覆盖读者最常问的问题）
const QUICK_QUESTIONS = [
  '这篇论文的主要贡献是什么？',
  '研究背景与动机是什么？',
  '方法和模型是如何设计的？',
  '核心实验结果有哪些？',
  '结论与未来工作方向是什么？',
  '这篇论文有哪些局限与不足？',
]

// 批注矩形（相对页面归一化坐标 0~1，缩放时自动适配）
interface HlRect {
  x: number
  y: number
  w: number
  h: number
}

// ---------------------------------------------------------------------------
// PDF 渲染性能与清晰度配置（借鉴 pdf.js 官方 viewer 的手法）
// 1. devicePixelRatio 上限 2：高分屏清晰的同时防止超大 canvas 撑爆显存
//    （scale=3 × dpr=3 时一张 A4 canvas 超 5000 万像素）
// 2. 缩放档位：离散步进，方便精确控制且避免连续小数重渲染
// 3. 缩放/resize 防抖：连续操作只触发一次 canvas 重渲染
// ---------------------------------------------------------------------------
const PDF_DEVICE_PIXEL_RATIO = Math.min(window.devicePixelRatio || 1, 2)
const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3]
const RESIZE_DEBOUNCE_MS = 200
// 单页 canvas 总像素上限（约 4096×4096）：高倍缩放 × 高分屏时线性回退 dpr，
// 防止超大 canvas 撑爆显存导致页面卡死（pdf.js viewer 的 maxCanvasPixels 同款手法）
const MAX_CANVAS_PIXELS = 16_777_216

// 可选的标注颜色（沿用 Zotero 官方 PDF 批注调色板，共 8 色）
const HIGHLIGHT_COLORS = ['#ffd400', '#ff6666', '#5fb236', '#2ea8e5', '#a28ae5', '#e56eee', '#f19837', '#aaaaaa']
const HIGHLIGHT_COLOR_LABELS: Record<string, string> = {
  '#ffd400': '黄',
  '#ff6666': '红',
  '#5fb236': '绿',
  '#2ea8e5': '蓝',
  '#a28ae5': '紫',
  '#e56eee': '洋红',
  '#f19837': '橙',
  '#aaaaaa': '灰',
}

const annotationTypeLabel: Record<string, string> = {
  highlight: '高亮',
  underline: '下划线',
  note: '笔记',
  summary: '总结',
}

// 从批注的 position JSON 中安全读取颜色 / 矩形
function annColor(ann: Annotation): string {
  const c = (ann.position as any)?.color
  return typeof c === 'string' && c ? c : '#ffd400'
}
function annRects(ann: Annotation): HlRect[] {
  const r = (ann.position as any)?.rects
  return Array.isArray(r) ? (r as HlRect[]) : []
}

// 侧栏批注面板：颜色筛选（Zotero Selector）+ 标注列表（点击跳转 + 右键菜单 + 评论/标签）
function AnnotationsPanel(props: {
  annotations: Annotation[]
  filterColors: string[]
  onToggleColor: (c: string) => void
  onClearFilter: () => void
  onJump: (ann: Annotation) => void
  onChangeColor: (ids: string[], color: string) => void
  onEditComment: (ann: Annotation) => void
  onDelete: (id: string) => void
}) {
  const { annotations, filterColors } = props
  const filtered = filterColors.length
    ? annotations.filter((a) => filterColors.includes(annColor(a)))
    : annotations

  return (
    <div>
      {/* 颜色筛选器（Zotero 式：点选颜色过滤批注） */}
      {annotations.length > 0 && (
        <div style={{ borderBottom: '1px solid #f0f0f0', paddingBottom: 10, marginBottom: 8 }}>
          <Space size={4} wrap>
            {HIGHLIGHT_COLORS.map((c) => {
              const active = filterColors.includes(c)
              return (
                <Tooltip key={c} title={HIGHLIGHT_COLOR_LABELS[c]}>
                  <div
                    onClick={() => props.onToggleColor(c)}
                    style={{
                      width: 18,
                      height: 18,
                      borderRadius: 4,
                      background: c,
                      cursor: 'pointer',
                      border: active ? '2px solid #333' : '1px solid #ccc',
                      opacity: annotations.some((a) => annColor(a) === c) ? 1 : 0.35,
                    }}
                  />
                </Tooltip>
              )
            })}
            {filterColors.length > 0 && (
              <a onClick={props.onClearFilter} style={{ fontSize: 12 }}>
                清除筛选
              </a>
            )}
          </Space>
        </div>
      )}

      <List
        dataSource={filtered}
        locale={{ emptyText: <Empty description={filterColors.length ? '无匹配的批注' : '还没有批注'} /> }}
        renderItem={(ann) => (
          <List.Item
            style={{ cursor: 'pointer', padding: '10px 4px' }}
            onClick={() => props.onJump(ann)}
          >
            <List.Item.Meta
              title={
                <Space wrap>
                  <span
                    style={{
                      display: 'inline-block',
                      width: 10,
                      height: 10,
                      borderRadius: 2,
                      background: annColor(ann),
                    }}
                  />
                  <Typography.Text strong style={{ fontSize: 13 }}>
                    {annotationTypeLabel[ann.type] || ann.type}
                  </Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    第 {ann.page_number ?? '-'} 页
                  </Typography.Text>
                  {ann.tags && ann.tags.length > 0 && (
                    <Space size={4} wrap>
                      {(ann.tags as string[]).map((t) => (
                        <Tag key={t} style={{ fontSize: 11, marginInlineEnd: 0 }}>
                          {t}
                        </Tag>
                      ))}
                    </Space>
                  )}
                </Space>
              }
              description={
                <div>
                  <div style={{ fontSize: 13, color: '#333' }}>{ann.content || '（原文内容）'}</div>
                  {ann.comment ? (
                    <div
                      style={{
                        marginTop: 6,
                        padding: '6px 8px',
                        background: '#f6f8fa',
                        borderRadius: 4,
                        fontSize: 12,
                        borderLeft: `3px solid ${annColor(ann)}`,
                        whiteSpace: 'pre-wrap',
                      }}
                    >
                      {ann.comment}
                    </div>
                  ) : (
                    ann.type !== 'note' && (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        点击「⋯」可添加评论
                      </Typography.Text>
                    )
                  )}
                </div>
              }
            />
            <Dropdown
              trigger={['contextMenu', 'click']}
              menu={{
                items: [
                  ...(ann.type !== 'note' && ann.type !== 'summary' && ann.type !== 'ink'
                    ? [
                        { key: 'comment', label: '编辑评论' },
                        ...HIGHLIGHT_COLORS.map((c) => ({
                          key: `color-${c}`,
                          label: (
                            <span>
                              <span
                                style={{
                                  display: 'inline-block',
                                  width: 10,
                                  height: 10,
                                  borderRadius: 2,
                                  background: c,
                                  marginRight: 6,
                                }}
                              />
                              {HIGHLIGHT_COLOR_LABELS[c]}
                            </span>
                          ),
                        })),
                        { type: 'divider' as const },
                      ]
                    : []),
                  {
                    key: 'delete',
                    danger: true,
                    label: '删除批注',
                  },
                ],
                onClick: ({ key, domEvent }) => {
                  domEvent.stopPropagation()
                  if (key === 'comment') {
                    props.onEditComment(ann)
                  } else if (key.startsWith('color-')) {
                    const color = key.replace('color-', '')
                    if (ann.id) props.onChangeColor([ann.id], color)
                  } else if (key === 'delete') {
                    if (ann.id) props.onDelete(ann.id)
                  }
                },
              }}
            >
              <Button type="text" size="small" icon={<MoreOutlined />} onClick={(e) => e.stopPropagation()} />
            </Dropdown>
          </List.Item>
        )}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Pin 卡片笔记面板（Q1-1）
// 每个 Annotation.note（comment 非空）渲染为一张小卡片：
//  - 显示 snippet + note 缩略 + 页码 + 色条
//  - 点击卡片 = 平滑 scroll 到该页 + 对应 rects 临时高亮 + 矩形边框脉冲闪烁 1 次
//  - 卡片可拖拽重排序（同文献内）；编辑 note / 删除 / 发送到写作
// ---------------------------------------------------------------------------
function PinCardsPanel(props: {
  cards: PinCard[]
  onJump: (card: PinCard) => void
  onEdit: (card: PinCard) => void
  onDelete: (id: string) => void
  onSend: (card: PinCard) => void
  onReorder: (from: number, to: number) => void
}) {
  const { cards } = props
  const [dragIdx, setDragIdx] = useState<number | null>(null)
  const [overIdx, setOverIdx] = useState<number | null>(null)

  if (cards.length === 0) {
    return (
      <Empty description="还没有卡片笔记。在 PDF 中选中文字后，点击「📌 钉成卡片」即可创建。" />
    )
  }

  return (
    <div style={{ maxHeight: 560, overflow: 'auto', paddingRight: 4 }}>
      {cards.map((card, idx) => {
        const dragging = dragIdx === idx
        const over = overIdx === idx && !dragging
        return (
          <div
            key={card.id}
            draggable
            onDragStart={(e) => {
              setDragIdx(idx)
              e.dataTransfer.effectAllowed = 'move'
            }}
            onDragOver={(e) => {
              e.preventDefault()
              setOverIdx(idx)
            }}
            onDragLeave={() => setOverIdx((v) => (v === idx ? null : v))}
            onDrop={(e) => {
              e.preventDefault()
              props.onReorder(dragIdx ?? -1, idx)
              setDragIdx(null)
              setOverIdx(null)
            }}
            onDragEnd={() => {
              setDragIdx(null)
              setOverIdx(null)
            }}
            style={{
              marginBottom: 10,
              borderRadius: 8,
              border: `1px solid ${over ? card.color : '#eee'}`,
              borderLeft: `4px solid ${card.color || '#ffd400'}`,
              background: dragging ? '#f0f5ff' : '#fff',
              boxShadow: dragging ? '0 2px 8px rgba(79,70,229,0.2)' : '0 1px 2px rgba(0,0,0,0.05)',
              padding: '8px 10px',
              cursor: 'grab',
              opacity: dragging ? 0.7 : 1,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 6 }}>
              <HolderOutlined style={{ color: '#bbb', marginTop: 2, fontSize: 12 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                {/* 原文 snippet 缩略（点击跳回原文） */}
                <div
                  onClick={() => props.onJump(card)}
                  title="点击跳回原文位置"
                  style={{
                    fontSize: 12,
                    color: '#555',
                    lineHeight: 1.5,
                    maxHeight: 40,
                    overflow: 'hidden',
                    cursor: 'pointer',
                  }}
                >
                  {card.snippet || '（无原文摘录）'}
                </div>
                {/* note 缩略（点击编辑） */}
                {card.note ? (
                  <div
                    onClick={() => props.onEdit(card)}
                    title="点击编辑卡片笔记"
                    style={{
                      marginTop: 4,
                      fontSize: 13,
                      color: '#1f2329',
                      lineHeight: 1.5,
                      maxHeight: 60,
                      overflow: 'hidden',
                      whiteSpace: 'pre-wrap',
                      cursor: 'pointer',
                    }}
                  >
                    {card.note}
                  </div>
                ) : (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    暂无笔记
                  </Typography.Text>
                )}
                {/* 页码 + 文献来源 */}
                <div style={{ marginTop: 4, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <Tag style={{ fontSize: 11, marginInlineEnd: 0 }} color="blue">
                    p{card.page ?? '-'}
                  </Tag>
                  <Typography.Text
                    type="secondary"
                    style={{ fontSize: 11, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  >
                    {card.paper_title}
                  </Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 11, whiteSpace: 'nowrap' }}>
                    {card.anchor}
                  </Typography.Text>
                </div>
                {/* 操作按钮：编辑 / 删除 / 发送到写作 */}
                <div style={{ marginTop: 6, display: 'flex', gap: 4 }}>
                  <Button
                    size="small"
                    type="text"
                    icon={<EditOutlined />}
                    onClick={() => props.onEdit(card)}
                  >
                    编辑
                  </Button>
                  <Button
                    size="small"
                    type="text"
                    icon={<SendOutlined />}
                    onClick={() => props.onSend(card)}
                  >
                    发送到写作
                  </Button>
                  <Button
                    size="small"
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => props.onDelete(card.id)}
                  />
                </div>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function ReaderPage() {
  const { paperId } = useParams<{ paperId: string }>()
  const navigate = useNavigate()
  // Smart Graph / 引用来源跳转：?page=N 直达指定页（优先于上次阅读进度）
  const [searchParams] = useSearchParams()
  const jumpPage = Number(searchParams.get('page')) || 0
  const [paper, setPaper] = useState<Paper | null>(null)
  const [numPages, setNumPages] = useState(0)
  const [pageNumber, setPageNumber] = useState(1)
  const [loading, setLoading] = useState(true)
  const [pdfSrc, setPdfSrc] = useState<Blob | null>(null)

  const [annotations, setAnnotations] = useState<Annotation[]>([])
  const [chatMessages, setChatMessages] = useState<ChatMsg[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  // DeepL 式悬浮翻译卡：选中文字后立即在选区附近展示译文
  const [floatTranslation, setFloatTranslation] = useState<{
    x: number
    y: number
    text: string
    result: string
  } | null>(null)
  const [translatingPdf, setTranslatingPdf] = useState(false)
  const [summary, setSummary] = useState('')
  const [summaryLoading, setSummaryLoading] = useState(false)
  const [tab, setTab] = useState('analysis')

  const [analysis, setAnalysis] = useState<PaperAnalysis | null>(null)
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [reanalyzing, setReanalyzing] = useState(false)

  const [selection, setSelection] = useState<{ text: string; x: number; y: number; rects: HlRect[] } | null>(null)
  const [hlColor, setHlColor] = useState<string>(HIGHLIGHT_COLORS[0])
  const [noteModal, setNoteModal] = useState<{ open: boolean; value: string }>({ open: false, value: '' })
  // 侧栏批注筛选（沿用 Zotero：按颜色多选过滤）
  const [filterColors, setFilterColors] = useState<string[]>([])
  // 编辑批注评论弹窗（Zotero 式：为高亮/下划线附上个人理解）
  const [commentModal, setCommentModal] = useState<{ open: boolean; id?: string; value: string }>({
    open: false,
    value: '',
  })
  // 引文导出弹窗
  const [citation, setCitation] = useState<{ citation: string; format: string; filename: string } | null>(null)

  // ---- Pin 卡片笔记（Q1-1）----
  const [pinCards, setPinCards] = useState<PinCard[]>([])
  // 划词工具条「📌 钉成卡片」笔记输入弹窗
  const [pinNoteModal, setPinNoteModal] = useState<{ open: boolean; value: string }>({ open: false, value: '' })
  // 卡片 note 编辑弹窗
  const [editCardModal, setEditCardModal] = useState<{ open: boolean; id?: string; value: string }>({
    open: false,
    value: '',
  })
  // 「发送到写作」：选择写作项目
  const [sendModal, setSendModal] = useState<{ open: boolean; cardId?: string }>({ open: false })
  const [projects, setProjects] = useState<Project[]>([])
  const [sendProjectId, setSendProjectId] = useState<string | undefined>(undefined)

  const containerRef = useRef<HTMLDivElement>(null)
  const pageWrapRef = useRef<HTMLDivElement>(null)
  // 当前页内批注矩形，用于点击侧栏批注时闪烁定位
  const flashTimerRef = useRef<number | null>(null)
  const [flashAnnId, setFlashAnnId] = useState<string | null>(null)
  // 引用溯源跳转：整页高亮闪烁（点击 AI 回答中的 [pN] 触发）
  const [citationFlash, setCitationFlash] = useState<number | null>(null)
  const citationTimerRef = useRef<number | null>(null)

  // ---- 缩放与自适应渲染（修复模糊 + 提升翻页流畅度）----
  // 模糊根因：此前固定渲染 700px 宽，宽屏上文字按小尺寸光栅化后再被放大。
  // 现在按容器实际宽度渲染（fit-width 起始），canvas 物理像素 = CSS × dpr。
  const [scale, setScale] = useState(1)               // 用户缩放系数（相对容器宽）
  const [containerWidth, setContainerWidth] = useState(0)  // 容器内容宽（ResizeObserver）
  const [renderWidth, setRenderWidth] = useState(0)   // 防抖后的实际渲染宽度
  // 每页宽高比表（预渲染阶段记录，用于固定容器高度避免翻页布局跳动）：
  // 若只在"成为当前页"时记录，预渲染页的回调不会再次触发，高度将停留旧值
  const [pageRatios, setPageRatios] = useState<Record<number, number>>({})
  const pageRatio = pageRatios[pageNumber] ?? 1.414
  const widthTimerRef = useRef<number | null>(null)

  // 容器尺寸监听：初始即「适应宽度」，窗口 resize 时自适应（防抖 200ms）
  useEffect(() => {
    if (loading) return
    const el = containerRef.current
    if (!el) return
    const apply = () => setContainerWidth(Math.max(320, el.clientWidth - 32))
    apply()
    let t: number | null = null
    const ro = new ResizeObserver(() => {
      if (t) window.clearTimeout(t)
      t = window.setTimeout(apply, RESIZE_DEBOUNCE_MS)
    })
    ro.observe(el)
    return () => {
      ro.disconnect()
      if (t) window.clearTimeout(t)
    }
  }, [loading])

  // 目标渲染宽度 = 容器宽 × 缩放；防抖提交，连续缩放/resize 只重渲染一次
  // （首次设置立即生效，不等待防抖，避免打开阅读器时空白 200ms）
  useEffect(() => {
    if (!containerWidth) return
    const w = Math.round(containerWidth * scale)
    if (renderWidth === 0 || renderWidth === w) {
      setRenderWidth(w)
      return
    }
    if (widthTimerRef.current) window.clearTimeout(widthTimerRef.current)
    widthTimerRef.current = window.setTimeout(() => setRenderWidth(w), RESIZE_DEBOUNCE_MS)
    return () => {
      if (widthTimerRef.current) window.clearTimeout(widthTimerRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [containerWidth, scale])

  // 缩放控制：档位步进 + 适应宽度
  const zoomIn = () => {
    const next = ZOOM_STEPS.find((s) => s > scale + 0.01)
    if (next) setScale(next)
  }
  const zoomOut = () => {
    const prev = [...ZOOM_STEPS].reverse().find((s) => s < scale - 0.01)
    if (prev) setScale(prev)
  }
  const zoomFitWidth = () => setScale(1)

  // 实际生效的 dpr：像素总量超上限时线性回退（高倍缩放保护）
  const effectiveDpr = useMemo(() => {
    const cssPixels = renderWidth * renderWidth * pageRatio
    if (cssPixels <= 0) return PDF_DEVICE_PIXEL_RATIO
    const cap = Math.sqrt(MAX_CANVAS_PIXELS / cssPixels)
    return Math.max(1, Math.min(PDF_DEVICE_PIXEL_RATIO, cap))
  }, [renderWidth, pageRatio])

  // 预渲染窗口：当前页 ±1（借鉴 pdf.js viewer 的页面 buffer）。
  // 翻页时目标页 canvas 已在后台渲染完成，切换 visibility 即刻显示，零白屏。
  const windowPages = useMemo(() => {
    if (!numPages) return []
    const pages: number[] = []
    for (const p of [pageNumber - 1, pageNumber, pageNumber + 1]) {
      if (p >= 1 && p <= numPages) pages.push(p)
    }
    return pages
  }, [pageNumber, numPages])

  // 键盘翻页：←/→ 或 PageUp/PageDown（输入框聚焦时不触发）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement)?.isContentEditable) return
      if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
        setPageNumber((p) => Math.max(1, p - 1))
      } else if (e.key === 'ArrowRight' || e.key === 'PageDown') {
        setPageNumber((p) => Math.min(numPages || 1, p + 1))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [numPages])

  useEffect(() => {
    if (!paperId) return
    setLoading(true)
    // 切换文献时清空上一份文档的页面宽高比表
    setPageRatios({})
    papersApi
      .get(paperId)
      .then((p) => {
        setPaper(p)
        // 长期记忆恢复：上次 AI 总结 + 上次阅读页码（?page= 跳转参数优先）
        if (p.summary) setSummary(p.summary)
        if (jumpPage > 0) setPageNumber(jumpPage)
        else if (p.last_page && p.last_page > 0) setPageNumber(p.last_page)
      })
      .catch((err) => message.error(getErrorMessage(err)))
      .finally(() => setLoading(false))
    annotationsApi
      .list(paperId)
      .then(setAnnotations)
      .catch((err) => message.error(getErrorMessage(err)))
    // 长期记忆恢复：上次的论文对话记录
    papersApi
      .chatHistory(paperId)
      .then((msgs) => setChatMessages(msgs))
      .catch(() => {
        /* 历史加载失败不阻塞阅读 */
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paperId])

  // 阅读进度自动保存：翻页时防抖 1.5s 落库（退出/刷新也不会丢）
  useEffect(() => {
    if (!paperId || loading || pageNumber < 1) return
    const t = window.setTimeout(() => {
      papersApi.saveProgress(paperId, pageNumber).catch(() => {
        /* 进度保存失败静默（不打扰阅读） */
      })
    }, 1500)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paperId, pageNumber, loading])

  // 用带鉴权的请求获取 PDF 文件的 Blob，直接交给 react-pdf 渲染（文件接口需要登录）。
  // 不再转成 blob URL——react-pdf 对 Blob 会走 loadFromFile -> {data} 路径，
  // 避免用 XHR 加载 blob URL 时响应头为空而触发 pdf.js 的
  // "Failed to construct 'Headers': Invalid name" 报错。
  useEffect(() => {
    if (!paperId) return
    let cancelled = false
    api
      .get(`/papers/${paperId}/file`, { responseType: 'blob' })
      .then(({ data }) => {
        if (!cancelled) setPdfSrc(data)
      })
      .catch((err) => message.error(getErrorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [paperId])

  // 本页需要渲染的批注（带矩形坐标、且属于当前页）
  const pageHighlights = useMemo(
    () =>
      annotations.filter(
        (a) =>
          a.page_number === pageNumber &&
          (a.type === 'highlight' || a.type === 'underline') &&
          annRects(a).length > 0,
      ),
    [annotations, pageNumber],
  )

  const onMouseUp = () => {
    const sel = window.getSelection()
    const text = sel?.toString().trim()
    if (text && text.length > 1 && pageWrapRef.current && containerRef.current) {
      const range = sel!.getRangeAt(0)
      const pageRect = pageWrapRef.current.getBoundingClientRect()
      // 把选区对应的每个矩形换算成页面归一化坐标，缩放时高亮仍能对齐文字
      const rects: HlRect[] = []
      for (let i = 0; i < range.getClientRects().length; i++) {
        const r = range.getClientRects()[i]
        rects.push({
          x: (r.left - pageRect.left) / pageRect.width,
          y: (r.top - pageRect.top) / pageRect.height,
          w: r.width / pageRect.width,
          h: r.height / pageRect.height,
        })
      }
      const rc = range.getBoundingClientRect()
      const containerRect = containerRef.current.getBoundingClientRect()
      // 算入容器滚动偏移：放大后容器可滚动，弹窗需相对内容区定位而非视口
      const scrollX = containerRef.current.scrollLeft
      const scrollY = containerRef.current.scrollTop
      setSelection({
        text,
        rects,
        x: rc.left - containerRect.left + scrollX + rc.width / 2,
        y: rc.top - containerRect.top + scrollY - 10,
      })
    } else {
      setSelection(null)
    }
  }

  const clearSelection = () => {
    setSelection(null)
    window.getSelection()?.removeAllRanges()
  }

  // 点击侧栏批注 → 跳到对应 PDF 页，并让该批注闪烁一下（Zotero 式定位）
  const jumpToAnnotation = (ann: Annotation) => {
    if (!ann.page_number) return
    setPageNumber(ann.page_number)
    setFlashAnnId(ann.id ?? null)
    if (flashTimerRef.current) window.clearTimeout(flashTimerRef.current)
    flashTimerRef.current = window.setTimeout(() => setFlashAnnId(null), 1200)
  }

  // 批量修改批注颜色（Zotero 式：右键菜单改色）
  const changeAnnotationColor = async (ids: string[], color: string) => {
    try {
      await Promise.all(
        ids.map((id) =>
          annotationsApi.update(id, {
            color,
            position: { ...((annotations.find((a) => a.id === id)?.position as any) || {}), color },
          }),
        ),
      )
      setAnnotations((prev) => prev.map((a) => (ids.includes(a.id!) ? { ...a, color } : a)))
      message.success('已更新颜色')
    } catch (err) {
      message.error(getErrorMessage(err))
    }
  }

  const openCommentEditor = (ann: Annotation) => {
    setCommentModal({ open: true, id: ann.id, value: ann.comment ?? '' })
  }

  const saveComment = async () => {
    const { id, value } = commentModal
    if (!id) return
    setCommentModal((m) => ({ ...m, open: false }))
    try {
      await annotationsApi.update(id, { comment: value })
      setAnnotations((prev) => prev.map((a) => (a.id === id ? { ...a, comment: value } : a)))
      message.success('已保存评论')
    } catch (err) {
      message.error(getErrorMessage(err))
    }
  }

  // ---- Pin 卡片笔记：数据加载 / 创建 / 编辑 / 删除 / 排序 / 跳转 / 发送到写作 ----
  const loadPinCards = async () => {
    try {
      setPinCards(await annotationsApi.listPinCards())
    } catch (err) {
      message.error(getErrorMessage(err))
    }
  }

  // 首次进入「卡片笔记」标签时加载（此后由各操作本地维护）
  useEffect(() => {
    if (tab === 'pin-cards' && pinCards.length === 0) loadPinCards()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  // 跨文献卡片跳转：目标文献页通过 ?flash=<annotation_id> 在加载后闪烁定位
  const flashParam = searchParams.get('flash')
  useEffect(() => {
    if (!flashParam) return
    setFlashAnnId(flashParam)
    if (flashTimerRef.current) window.clearTimeout(flashTimerRef.current)
    flashTimerRef.current = window.setTimeout(() => setFlashAnnId(null), 1400)
  }, [flashParam])

  // 「📌 钉成卡片」：划词 → 输入笔记 → 保存为 高亮 + comment（后端 /annotations/pins 以此作为卡片）
  const handlePinCard = () => {
    if (!selection) return
    setPinNoteModal({ open: true, value: '' })
  }

  const confirmPinNote = async () => {
    const note = pinNoteModal.value.trim()
    if (!note) {
      message.warning('请输入卡片笔记内容')
      return
    }
    setPinNoteModal((m) => ({ ...m, open: false }))
    if (!paperId || !selection) return
    const position = { rects: selection.rects, color: hlColor }
    try {
      const ann = await annotationsApi.create({
        paper_id: paperId,
        type: 'highlight',
        content: selection.text,
        comment: note,
        page_number: pageNumber,
        position,
      })
      setAnnotations((prev) => [ann, ...prev])
      loadPinCards()
      message.success('已钉成卡片')
    } catch (err) {
      message.error(getErrorMessage(err))
    }
    clearSelection()
  }

  // 点击卡片 → 跳回原文位置：同文献直接翻页闪烁；跨文献跳转后在目标页闪烁
  const jumpToPinCard = (card: PinCard) => {
    if (!card.page) return
    if (card.paper_id === paperId) {
      setPageNumber(card.page)
      setFlashAnnId(card.id)
      if (flashTimerRef.current) window.clearTimeout(flashTimerRef.current)
      flashTimerRef.current = window.setTimeout(() => setFlashAnnId(null), 1400)
    } else {
      navigate(`/reader/${card.paper_id}?page=${card.page}&flash=${card.id}`)
    }
  }

  const openEditCard = (card: PinCard) => {
    setEditCardModal({ open: true, id: card.id, value: card.note })
  }

  const saveEditCard = async () => {
    const { id, value } = editCardModal
    if (!id) return
    setEditCardModal((m) => ({ ...m, open: false }))
    try {
      await annotationsApi.update(id, { comment: value })
      setPinCards((prev) => prev.map((c) => (c.id === id ? { ...c, note: value } : c)))
      setAnnotations((prev) => prev.map((a) => (a.id === id ? { ...a, comment: value } : a)))
      message.success('已更新卡片笔记')
    } catch (err) {
      message.error(getErrorMessage(err))
    }
  }

  const deletePinCard = (id: string) => {
    Modal.confirm({
      title: '删除卡片笔记？',
      content: '该卡片及其原文高亮将被删除，且不可恢复。',
      okText: '删除',
      cancelText: '取消',
      okType: 'danger',
      onOk: async () => {
        try {
          await annotationsApi.remove(id)
          setPinCards((prev) => prev.filter((c) => c.id !== id))
          setAnnotations((prev) => prev.filter((a) => a.id !== id))
          message.success('已删除卡片')
        } catch (err) {
          message.error(getErrorMessage(err))
        }
      },
    })
  }

  // 拖拽重排：仅允许同一篇文献的卡片互相排序（与后端「按文献分组」一致）
  const reorderPinCards = (from: number, to: number) => {
    const fromCard = pinCards[from]
    const toCard = pinCards[to]
    if (!fromCard || !toCard || fromCard.paper_id !== toCard.paper_id) {
      message.warning('只能在同一篇文献的卡片之间拖拽排序')
      return
    }
    const next = [...pinCards]
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    setPinCards(next)
    annotationsApi
      .reorder(next.map((c) => ({ id: c.id })))
      .catch((err) => message.error(getErrorMessage(err)))
  }

  // 发送到写作：选择写作项目
  const openSendCard = (card: PinCard) => {
    projectsApi
      .list()
      .then((projs) => {
        setProjects(projs)
        setSendProjectId(projs[0]?.id)
        setSendModal({ open: true, cardId: card.id })
      })
      .catch((err) => message.error(getErrorMessage(err)))
  }

  const confirmSendCard = async () => {
    const cardId = sendModal.cardId
    if (!cardId || !sendProjectId) {
      message.warning('请选择写作项目')
      return
    }
    setSendModal((m) => ({ ...m, open: false }))
    try {
      const res = await annotationsApi.sendToWriting(cardId, sendProjectId)
      message.success(`已发送到写作项目（引用：${res.anchor}）`)
    } catch (err) {
      message.error(getErrorMessage(err))
    }
  }

  // 引文导出（Zotero：一键复制/下载引文）
  const exportCitation = async (format: 'bibtex' | 'biblatex' | 'gb7714') => {
    if (!paperId) return
    try {
      const res = await papersApi.citation(paperId, format)
      setCitation(res)
    } catch (err) {
      message.error(getErrorMessage(err))
    }
  }

  const downloadCitation = () => {
    if (!citation) return
    const blob = new Blob([citation.citation], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = citation.filename
    a.click()
    URL.revokeObjectURL(url)
  }

  // BabelDOC 整篇翻译：保持原版式输出双语 PDF
  const translateWholePdf = async () => {
    if (!paperId || translatingPdf) return
    setTranslatingPdf(true)
    try {
      const blob = await translateApi.translatePdf(paperId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${paper?.title || 'paper'}-translated.pdf`
      a.click()
      URL.revokeObjectURL(url)
      message.success('整篇翻译完成，已开始下载双语 PDF')
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setTranslatingPdf(false)
    }
  }

  // 保存一条带颜色 + 矩形坐标的标注
  const saveAnnotation = async (type: Annotation['type'], content?: string) => {
    if (!paperId || !selection) return
    const position = {
      rects: selection.rects,
      color: hlColor,
    }
    try {
      const ann = await annotationsApi.create({
        paper_id: paperId,
        type,
        content: content ?? selection.text,
        page_number: pageNumber,
        position,
      })
      setAnnotations((prev) => [ann, ...prev])
      message.success('已保存标注')
    } catch (err) {
      message.error(getErrorMessage(err))
    }
    clearSelection()
  }

  const handleHighlight = () => saveAnnotation('highlight')
  const handleUnderline = () => saveAnnotation('underline')

  const handleNote = () => {
    if (!selection) return
    setNoteModal({ open: true, value: selection.text })
  }

  const confirmNote = async () => {
    const content = noteModal.value.trim()
    if (!content) {
      message.warning('请输入笔记内容')
      return
    }
    setNoteModal((m) => ({ ...m, open: false }))
    await saveAnnotation('note', content)
  }

  const handleTranslate = async () => {
    if (!selection) return
    const text = selection.text
    setFloatTranslation({
      x: selection.x,
      y: selection.y + 26,
      text,
      result: '',
    })
    try {
      if (text.length <= 300) {
        // 短句/术语：直接返回完整译文，避免逐 token 等待
        const res = await translateApi.translate(text, 'zh')
        setFloatTranslation((f) => (f ? { ...f, result: res.translation } : f))
      } else {
        await translateApi.translateStream(text, 'zh', (delta) => {
          setFloatTranslation((f) => (f ? { ...f, result: f.result + delta } : f))
        })
      }
    } catch (err) {
      message.error(getErrorMessage(err))
    }
  }

  const handleExplain = async () => {
    if (!selection) return
    const text = selection.text
    clearSelection()
    setTab('ai')
    const question = `解释术语："${text}"`
    setChatMessages((prev) => [...prev, { role: 'user', content: question }])
    setChatMessages((prev) => [...prev, { role: 'assistant', content: '' }])
    setChatLoading(true)
    let answer = ''
    try {
      await termApi.lookupStream(text, false, (delta) => {
        answer += delta
        setChatMessages((prev) => {
          const copy = [...prev]
          const last = copy[copy.length - 1]
          copy[copy.length - 1] = { ...last, content: (last?.content || '') + delta }
          return copy
        })
      })
      // 术语解释结果入档（长期记忆：重开界面仍可见）
      if (paperId && answer) {
        papersApi.appendChat(paperId, 'user', question).catch(() => {})
        papersApi.appendChat(paperId, 'assistant', answer).catch(() => {})
      }
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setChatLoading(false)
    }
  }

  const clearChat = async () => {
    if (!paperId || chatMessages.length === 0) return
    Modal.confirm({
      title: '清空对话记录？',
      content: '该论文的全部 AI 对话将被删除，且不可恢复。',
      okText: '清空',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await papersApi.clearChat(paperId)
          setChatMessages([])
          message.success('已清空对话')
        } catch (err) {
          message.error(getErrorMessage(err))
        }
      },
    })
  }

  // 点击 AI 回答中的引用 [pN] → 跳到 PDF 对应页并整页高亮闪烁
  const jumpToCitation = (page: number) => {
    if (!page || page < 1) return
    setPageNumber(page)
    setCitationFlash(page)
    if (citationTimerRef.current) window.clearTimeout(citationTimerRef.current)
    citationTimerRef.current = window.setTimeout(() => setCitationFlash(null), 1600)
  }

  const sendChat = async () => {
    if (!paperId || !chatInput.trim()) return
    const msg = chatInput.trim()
    setChatInput('')
    setChatMessages((prev) => [...prev, { role: 'user', content: msg }, { role: 'assistant', content: '' }])
    setChatLoading(true)
    try {
      await papersApi.chatStream(
        paperId,
        msg,
        (delta) => {
          setChatMessages((prev) => {
            const copy = [...prev]
            const last = copy[copy.length - 1]
            copy[copy.length - 1] = { ...last, content: (last?.content || '') + delta }
            return copy
          })
        },
        // 引用溯源：流结束后把检索到的来源（页码+片段）挂到该条回答上
        (meta) => {
          if (meta?.citations) {
            const citations = meta.citations
            setChatMessages((prev) => {
              const copy = [...prev]
              const last = copy[copy.length - 1]
              copy[copy.length - 1] = { ...last, citations }
              return copy
            })
          }
        },
      )
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setChatLoading(false)
    }
  }

  // 快捷提问：直接把预设问题填入并发送
  const sendQuickQuestion = (q: string) => {
    if (!paperId || chatLoading) return
    setChatInput('')
    setChatMessages((prev) => [...prev, { role: 'user', content: q }, { role: 'assistant', content: '' }])
    setChatLoading(true)
    papersApi
      .chatStream(
        paperId,
        q,
        (delta) => {
          setChatMessages((prev) => {
            const copy = [...prev]
            const last = copy[copy.length - 1]
            copy[copy.length - 1] = { ...last, content: (last?.content || '') + delta }
            return copy
          })
        },
        (meta) => {
          if (meta?.citations) {
            const citations = meta.citations
            setChatMessages((prev) => {
              const copy = [...prev]
              const last = copy[copy.length - 1]
              copy[copy.length - 1] = { ...last, citations }
              return copy
            })
          }
        },
      )
      .catch((err) => message.error(getErrorMessage(err)))
      .finally(() => setChatLoading(false))
  }

  const generateSummary = async (refresh = false) => {
    if (!paperId) return
    setSummaryLoading(true)
    try {
      const { summary: s } = await papersApi.summary(paperId, 'full', undefined, refresh)
      setSummary(s)
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setSummaryLoading(false)
    }
  }

  const loadAnalysis = async () => {
    if (!paperId) return
    setAnalysisLoading(true)
    try {
      const a = await papersApi.analysis(paperId)
      setAnalysis(a)
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setAnalysisLoading(false)
    }
  }

  const handleReanalyze = async () => {
    if (!paperId || reanalyzing) return
    setReanalyzing(true)
    try {
      await papersApi.reanalyze(paperId)
      message.success('已开始结构感知拆分，完成后自动刷新')
      setAnalysis((a) => (a ? { ...a, analysis_status: 'pending' } : a))
      loadAnalysis()
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setReanalyzing(false)
    }
  }

  // 首次进入「论文分析」标签时自动加载
  useEffect(() => {
    if (tab === 'analysis' && !analysis && !analysisLoading) {
      loadAnalysis()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  // AI 分析还在后台进行时，每 5s 自动刷新，完成后自动展示结果
  useEffect(() => {
    if (tab !== 'analysis' || !analysis || analysis.analysis_status !== 'pending') return
    const t = setInterval(loadAnalysis, 5000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, analysis?.analysis_status])

  const analysisContent = () => {
    if (analysisLoading && !analysis) {
      return (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin />
        </div>
      )
    }
    if (!analysis) {
      return (
        <div style={{ textAlign: 'center', padding: 24 }}>
          <Empty description="暂无分析数据" />
        </div>
      )
    }
    const dims = analysis.dimensions.filter((d) => d.content && d.content.trim())
    const meta = analysis.analysis_meta
    const topLevel = (meta?.top_level ?? []).filter((s) => s.kind !== 'references')
    return (
      <div style={{ maxHeight: 560, overflow: 'auto', paddingRight: 8 }}>
        <Typography.Title level={5}>AI 语义分析</Typography.Title>
        {meta && (
          <div
            style={{
              marginBottom: 14,
              padding: '8px 10px',
              background: '#f6f8fa',
              borderRadius: 6,
              border: '1px solid #eef1f5',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
              <Typography.Text strong style={{ fontSize: 13 }}>
                结构感知拆分
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {meta.chunking?.mode === 'structure' ? '已识别章节结构' : '段落级切分'} ·{' '}
                {meta.chunking?.text_chunks ?? 0} 个原文片段 · 重叠{' '}
                {meta.chunking?.overlap ?? 0} 字符
              </Typography.Text>
              <Button
                size="small"
                icon={<RedoOutlined />}
                onClick={handleReanalyze}
                loading={reanalyzing}
                disabled={analysis.analysis_status === 'pending'}
              >
                重新拆分
              </Button>
            </div>
            {topLevel.length > 0 && (
              <Space size={[4, 4]} wrap>
                {topLevel.map((s, idx) => (
                  <Tag key={`${s.title}-${idx}`} style={{ fontSize: 11, marginInlineEnd: 0 }}>
                    {s.title}
                  </Tag>
                ))}
              </Space>
            )}
          </div>
        )}
        {dims.length === 0 ? (
          analysis.analysis_status === 'pending' ? (
            <Typography.Text type="secondary">
              AI 正在后台解析这篇论文的语义维度，完成后将自动显示…（不影响你阅读正文）
            </Typography.Text>
          ) : (
            <Typography.Text type="secondary">该论文尚未完成维度拆分（状态：{analysis.status}）。</Typography.Text>
          )
        ) : (
          dims.map((d) => (
            <div
              key={d.dimension}
              style={{ marginBottom: 16, borderLeft: '3px solid #91caff', paddingLeft: 10 }}
            >
              <Space size={[4, 4]} wrap style={{ marginBottom: 4 }}>
                <Tag color="blue">{d.label}</Tag>
                {d.section && <Tag>{d.section}</Tag>}
                {(d.meta?.evidence_sections ?? []).slice(0, 3).map((ev, idx) => (
                  <Tag key={`${d.dimension}-${ev}-${idx}`} color="cyan" style={{ fontSize: 11 }}>
                    {ev}
                  </Tag>
                ))}
              </Space>
              <div style={{ whiteSpace: 'pre-wrap', marginTop: 4, fontSize: 13 }}>{d.content}</div>
            </div>
          ))
        )}

        <Divider />
        <Typography.Title level={5}>我的笔记（{analysis.user_notes.length}）</Typography.Title>
        {analysis.user_notes.length === 0 ? (
          <Typography.Text type="secondary">还没有阅读笔记，可在 PDF 中选中文字后添加。</Typography.Text>
        ) : (
          analysis.user_notes.map((n) => (
            <div key={n.id} style={{ marginBottom: 12, borderLeft: '3px solid #d9d9d9', paddingLeft: 10 }}>
              <Space size={4}>
                <Tag>{annotationTypeLabel[n.type] || n.type}</Tag>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  第 {n.page_number ?? '-'} 页
                </Typography.Text>
              </Space>
              <div style={{ whiteSpace: 'pre-wrap', marginTop: 4, fontSize: 13 }}>{n.content || '（空）'}</div>
            </div>
          ))
        )}
      </div>
    )
  }

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    )
  }

  if (!paper) {
    return <Empty description="未找到该文献" />
  }

  return (
    <div>
      <Row align="middle" style={{ marginBottom: 12 }}>
        <Col>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/library')}>
            返回
          </Button>
        </Col>
        <Col flex="auto" style={{ paddingLeft: 16 }}>
          <Typography.Title level={5} ellipsis style={{ margin: 0 }}>
            {paper.title}
          </Typography.Title>
          {paper.authors && <Typography.Text type="secondary">{paper.authors.join('、')}</Typography.Text>}
        </Col>
        <Col>
          <Space>
            <Dropdown
              menu={{
                items: [
                  { key: 'biblatex', label: 'BibLaTeX' },
                  { key: 'bibtex', label: 'BibTeX' },
                  { key: 'gb7714', label: 'GB/T 7714（国标）' },
                ],
                onClick: ({ key }) => exportCitation(key as 'bibtex' | 'biblatex' | 'gb7714'),
              }}
            >
              <Button icon={<ExportOutlined />}>导出引文</Button>
            </Dropdown>
            <Button
              icon={<GlobalOutlined />}
              loading={translatingPdf}
              onClick={translateWholePdf}
            >
              整篇翻译
            </Button>
            <Button onClick={() => setPageNumber((p) => Math.max(1, p - 1))} disabled={pageNumber <= 1}>
              上一页
            </Button>
            <span>
              {pageNumber} / {numPages || '?'}
            </span>
            <Button onClick={() => setPageNumber((p) => Math.min(numPages, p + 1))} disabled={pageNumber >= numPages}>
              下一页
            </Button>
            {/* 缩放控件 */}
            <Space.Compact>
              <Tooltip title="缩小（最小 50%）">
                <Button icon={<ZoomOutOutlined />} onClick={zoomOut} disabled={scale <= ZOOM_STEPS[0]} />
              </Tooltip>
              <Tooltip title="恢复适应宽度（100%）">
                <Button
                  icon={<ColumnWidthOutlined />}
                  onClick={zoomFitWidth}
                  style={{ minWidth: 64, fontWeight: 500 }}
                >
                  {Math.round(scale * 100)}%
                </Button>
              </Tooltip>
              <Tooltip title="放大（最大 300%）">
                <Button icon={<ZoomInOutlined />} onClick={zoomIn} disabled={scale >= ZOOM_STEPS[ZOOM_STEPS.length - 1]} />
              </Tooltip>
            </Space.Compact>
          </Space>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col xs={24} lg={16}>
          <div
            ref={containerRef}
            className="pdf-container"
            style={{ position: 'relative', minHeight: 400 }}
            onMouseUp={onMouseUp}
          >
            {pdfSrc && (
              <Document
                file={pdfSrc}
                onLoadSuccess={({ numPages }) => setNumPages(numPages)}
                onLoadError={(err) => message.error(getErrorMessage(err))}
                loading={<Spin />}
                options={PDF_OPTIONS}
              >
                {/* 预渲染窗口容器：固定高度（当前页宽高比）避免翻页时布局跳动。
                    margin auto 居中：放大超出容器时贴左可横向滚动（flex center 会裁掉左半） */}
                <div
                  ref={pageWrapRef}
                  style={{
                    position: 'relative',
                    width: renderWidth || undefined,
                    height: renderWidth ? Math.round(renderWidth * pageRatio) : undefined,
                    minHeight: 300,
                    margin: '0 auto',
                  }}
                >
                  {renderWidth > 0 &&
                    windowPages.map((p) => (
                      <div
                        key={p}
                        style={{
                          position: 'absolute',
                          top: 0,
                          left: 0,
                          // 仅当前页可见；相邻页隐藏但保持渲染（翻页零白屏）
                          visibility: p === pageNumber ? 'visible' : 'hidden',
                          zIndex: p === pageNumber ? 2 : 1,
                        }}
                      >
                        <Page
                          pageNumber={p}
                          width={renderWidth}
                          devicePixelRatio={effectiveDpr}
                          renderTextLayer
                          // 批注层（链接等）仅当前页需要，省去预渲染页的解析开销
                          renderAnnotationLayer={p === pageNumber}
                          loading={<Spin size="small" />}
                          onLoadSuccess={(page: any) => {
                            // 预渲染阶段即记录该页宽高比（翻页时高度立即可用）
                            if (page?.originalWidth > 0) {
                              const ratio = page.originalHeight / page.originalWidth
                              setPageRatios((prev) =>
                                prev[p] === ratio ? prev : { ...prev, [p]: ratio },
                              )
                            }
                          }}
                        />
                      </div>
                    ))}
                  {/* 直接在 PDF 上叠加渲染高亮 / 下划线（Zotero 式） */}
                  {pageHighlights.map((ann) => {
                    const color = annColor(ann)
                    const isUnderline = ann.type === 'underline'
                    const isFlash = flashAnnId === ann.id
                    return (annRects(ann) as HlRect[]).map((r, ri) => (
                      <div
                        key={`${ann.id}-${ri}`}
                        style={{
                          position: 'absolute',
                          left: `${r.x * 100}%`,
                          top: `${r.y * 100}%`,
                          width: `${r.w * 100}%`,
                          height: `${r.h * 100}%`,
                          background: isUnderline ? 'transparent' : `${color}66`,
                          borderBottom: isUnderline ? `2px solid ${color}` : 'none',
                          outline: isFlash ? `2px solid ${color}` : 'none',
                          boxShadow: isFlash ? `0 0 0 9999px rgba(0,0,0,0.15)` : 'none',
                          transition: 'outline 0.2s, box-shadow 0.2s',
                          // 卡片点击跳转：矩形边框脉冲闪烁 1 次（Q1-1）
                          animation: isFlash ? 'annotation-flash-pulse 1.3s ease-out' : 'none',
                          pointerEvents: 'none',
                          zIndex: isFlash ? 6 : 5,
                        }}
                      />
                    ))
                  })}
                  {/* 引用溯源跳转：整页高亮闪烁（pointerEvents 不挡文字选择） */}
                  {citationFlash === pageNumber && (
                    <div
                      style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        right: 0,
                        bottom: 0,
                        background: 'rgba(79, 70, 229, 0.10)',
                        boxShadow: 'inset 0 0 0 3px #4f46e5',
                        zIndex: 7,
                        pointerEvents: 'none',
                        animation: 'citation-pulse 1.6s ease-out',
                      }}
                    />
                  )}
                </div>
              </Document>
            )}

            {selection && (
              <div
                style={{
                  position: 'absolute',
                  left: Math.max(20, Math.min(selection.x - 140, (containerRef.current?.clientWidth || 700) - 300)),
                  top: selection.y,
                  zIndex: 10,
                }}
              >
                <div style={{ background: '#fff', padding: '6px 8px', borderRadius: 6, boxShadow: '0 2px 8px rgba(0,0,0,0.2)' }}>
                  {/* 颜色选择器 */}
                  <Space size={4} style={{ marginBottom: 4 }}>
                    {HIGHLIGHT_COLORS.map((c) => (
                      <Tooltip key={c} title={HIGHLIGHT_COLOR_LABELS[c]}>
                        <div
                          onClick={() => setHlColor(c)}
                          style={{
                            width: 18,
                            height: 18,
                            borderRadius: 4,
                            background: c,
                            cursor: 'pointer',
                            border: hlColor === c ? '2px solid #333' : '1px solid #ccc',
                          }}
                        />
                      </Tooltip>
                    ))}
                  </Space>
                  <Space size={4}>
                    <Button size="small" onClick={handleHighlight}>高亮</Button>
                    <Button size="small" onClick={handleUnderline}>下划线</Button>
                    <Button size="small" onClick={handleNote}>笔记</Button>
                    <Button size="small" type="primary" icon={<PushpinOutlined />} onClick={handlePinCard}>
                      钉成卡片
                    </Button>
                    <Button size="small" onClick={handleTranslate}>翻译</Button>
                    <Button size="small" onClick={handleExplain}>解释</Button>
                  </Space>
                </div>
              </div>
            )}

            {/* DeepL 式悬浮翻译卡 */}
            {floatTranslation && (
              <div
                style={{
                  position: 'absolute',
                  left: Math.max(20, Math.min(floatTranslation.x, (containerRef.current?.clientWidth || 700) - 400)),
                  top: Math.max(20, floatTranslation.y),
                  width: 380,
                  maxWidth: 'calc(100% - 40px)',
                  zIndex: 20,
                  background: '#fff',
                  border: '1px solid #e5e7eb',
                  borderRadius: 8,
                  boxShadow: '0 6px 20px rgba(0,0,0,0.16)',
                  padding: 10,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <Typography.Text strong style={{ fontSize: 12 }}>
                    中文翻译
                  </Typography.Text>
                  <Space size={4}>
                    <Button
                      size="small"
                      disabled={!floatTranslation.result}
                      onClick={() => {
                        navigator.clipboard.writeText(floatTranslation.result)
                        message.success('已复制译文')
                      }}
                    >
                      复制
                    </Button>
                    <Button size="small" type="text" onClick={() => setFloatTranslation(null)}>
                      关闭
                    </Button>
                  </Space>
                </div>
                <div style={{ fontSize: 13, lineHeight: 1.7, color: '#333', minHeight: 24 }}>
                  {floatTranslation.result || <Spin size="small" />}
                </div>
              </div>
            )}
          </div>
        </Col>

        <Col xs={24} lg={8}>
          <Tabs
            activeKey={tab}
            onChange={setTab}
            items={[
              {
                key: 'analysis',
                label: '论文分析',
                children: analysisContent(),
              },
              {
                key: 'annotations',
                label: `批注${annotations.length ? ` (${annotations.length})` : ''}`,
                children: <AnnotationsPanel
                  annotations={annotations}
                  filterColors={filterColors}
                  onToggleColor={(c) =>
                    setFilterColors((prev) =>
                      prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c],
                    )
                  }
                  onClearFilter={() => setFilterColors([])}
                  onJump={jumpToAnnotation}
                  onChangeColor={changeAnnotationColor}
                  onEditComment={openCommentEditor}
                  onDelete={(id) => {
                    annotationsApi
                      .remove(id)
                      .then(() => setAnnotations((prev) => prev.filter((a) => a.id !== id)))
                      .catch((err) => message.error(getErrorMessage(err)))
                  }}
                />,
              },
              {
                key: 'pin-cards',
                label: `卡片笔记${pinCards.length ? ` (${pinCards.length})` : ''}`,
                children: (
                  <PinCardsPanel
                    cards={pinCards}
                    onJump={jumpToPinCard}
                    onEdit={openEditCard}
                    onDelete={deletePinCard}
                    onSend={openSendCard}
                    onReorder={reorderPinCards}
                  />
                ),
              },
              {
                key: 'ai',
                label: `AI 助手${chatMessages.length ? ` (${chatMessages.length})` : ''}`,
                children: (
                  <div style={{ display: 'flex', flexDirection: 'column', height: 520 }}>
                    {/* 6 个快捷提问按钮：点击即发送预设问题 */}
                    <Space size={[6, 6]} wrap style={{ marginBottom: 8 }}>
                      {QUICK_QUESTIONS.map((q) => (
                        <Button
                          key={q}
                          size="small"
                          loading={chatLoading}
                          onClick={() => sendQuickQuestion(q)}
                        >
                          {q}
                        </Button>
                      ))}
                    </Space>
                    <div style={{ flex: 1, overflow: 'auto', paddingRight: 8 }}>
                      {chatMessages.length === 0 && (
                        <Typography.Text type="secondary">
                          可以点上方快捷提问，或直接输入问题，例如「它的主要贡献是什么？」
                          <br />
                          AI 回答会标注来源页码（如 [p3]），点击可跳转到 PDF 对应页。
                          <br />
                          对话会自动保存，下次打开继续聊。
                        </Typography.Text>
                      )}
                      {chatMessages.map((m, i) => (
                        <div
                          key={i}
                          style={{
                            margin: '8px 0',
                            textAlign: m.role === 'user' ? 'right' : 'left',
                          }}
                        >
                          <div
                            style={{
                              display: 'inline-block',
                              padding: '8px 12px',
                              borderRadius: 10,
                              background: m.role === 'user' ? '#4f46e5' : '#f0f0f0',
                              color: m.role === 'user' ? '#fff' : '#000',
                              maxWidth: '90%',
                              textAlign: 'left',
                            }}
                          >
                            <ReactMarkdown
                              components={{
                                // 拦截 [pN](cite:N) 链接：点击跳 PDF 页码高亮
                                a: ({ href, children }) => {
                                  if (href && href.startsWith('cite:')) {
                                    const page = Number(href.split(':')[1])
                                    if (page > 0) {
                                      return (
                                        <a
                                          onClick={(e) => {
                                            e.preventDefault()
                                            jumpToCitation(page)
                                          }}
                                          style={{
                                            color: '#4f46e5',
                                            cursor: 'pointer',
                                            fontWeight: 600,
                                            textDecoration: 'underline',
                                            margin: '0 2px',
                                          }}
                                        >
                                          {children}
                                        </a>
                                      )
                                    }
                                  }
                                  return <a href={href}>{children}</a>
                                },
                              }}
                            >
                              {formatMarkdownContent(
                                m.content.replace(/\[p(\d+)\]/g, (_s, p) => `[p${p}](cite:${p})`),
                              )}
                            </ReactMarkdown>
                            {/* 引用来源列表（点击页码跳转） */}
                            {m.citations && m.citations.length > 0 && (
                              <div
                                style={{
                                  marginTop: 8,
                                  padding: '6px 8px',
                                  background: '#eef2ff',
                                  borderRadius: 6,
                                  fontSize: 12,
                                  color: '#555',
                                }}
                              >
                                <div style={{ color: '#4f46e5', fontWeight: 600, marginBottom: 4 }}>
                                  引用来源（点击跳转）
                                </div>
                                {m.citations.map((c, ci) => (
                                  <div key={ci} style={{ marginBottom: 4, lineHeight: 1.5 }}>
                                    <a
                                      onClick={(e) => {
                                        e.preventDefault()
                                        if (c.page) jumpToCitation(c.page)
                                      }}
                                      style={{
                                        color: '#4f46e5',
                                        cursor: 'pointer',
                                        fontWeight: 600,
                                        marginRight: 6,
                                      }}
                                    >
                                      [p{c.page}]
                                    </a>
                                    {c.snippet}
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                      {chatLoading && <Spin />}
                    </div>
                    <Space.Compact style={{ marginTop: 8 }}>
                      <TextArea
                        value={chatInput}
                        onChange={(e) => setChatInput(e.target.value)}
                        placeholder="就这篇论文提问..."
                        autoSize={{ minRows: 1, maxRows: 3 }}
                        onPressEnter={(e) => {
                          if (!e.shiftKey) {
                            e.preventDefault()
                            sendChat()
                          }
                        }}
                      />
                      <Button type="primary" icon={<SendOutlined />} onClick={sendChat} loading={chatLoading} />
                      <Tooltip title="清空该论文的对话记录">
                        <Button
                          icon={<ClearOutlined />}
                          onClick={clearChat}
                          disabled={chatMessages.length === 0 || chatLoading}
                        />
                      </Tooltip>
                    </Space.Compact>
                  </div>
                ),
              },
              {
                key: 'summary',
                label: '总结',
                children: (
                  <div>
                    <Space style={{ marginBottom: 12 }}>
                      <Button
                        icon={<ThunderboltOutlined />}
                        onClick={() => generateSummary(false)}
                        loading={summaryLoading}
                      >
                        {summary ? '查看总结' : '生成全文总结'}
                      </Button>
                      {summary && (
                        <Button onClick={() => generateSummary(true)} disabled={summaryLoading}>
                          重新生成
                        </Button>
                      )}
                    </Space>
                    {summaryLoading ? (
                      <Spin />
                    ) : summary ? (
                      <div className="markdown-body">
                        <ReactMarkdown>{summary}</ReactMarkdown>
                      </div>
                    ) : (
                      <Empty description="点击按钮生成总结" />
                    )}
                  </div>
                ),
              },
            ]}
          />
        </Col>
      </Row>

      {/* 添加笔记弹窗 */}
      <Modal
        title="添加笔记"
        open={noteModal.open}
        onOk={confirmNote}
        onCancel={() => setNoteModal((m) => ({ ...m, open: false }))}
        okText="保存"
        cancelText="取消"
      >
        <TextArea
          value={noteModal.value}
          onChange={(e) => setNoteModal((m) => ({ ...m, value: e.target.value }))}
          rows={4}
          placeholder="输入你的笔记内容..."
          autoFocus
        />
      </Modal>

      {/* 钉成卡片弹窗（Q1-1：划词 → 输入笔记 → 存为卡片） */}
      <Modal
        title="📌 钉成卡片"
        open={pinNoteModal.open}
        onOk={confirmPinNote}
        onCancel={() => setPinNoteModal((m) => ({ ...m, open: false }))}
        okText="钉成卡片"
        cancelText="取消"
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          原文摘录：{selection?.text || ''}
        </Typography.Paragraph>
        <TextArea
          value={pinNoteModal.value}
          onChange={(e) => setPinNoteModal((m) => ({ ...m, value: e.target.value }))}
          rows={4}
          placeholder="写下你的卡片笔记（支持中文），保存后可在右侧「卡片笔记」面板集中管理与跳回原文。"
          autoFocus
        />
      </Modal>

      {/* 编辑卡片笔记弹窗（Q1-1） */}
      <Modal
        title="编辑卡片笔记"
        open={editCardModal.open}
        onOk={saveEditCard}
        onCancel={() => setEditCardModal((m) => ({ ...m, open: false }))}
        okText="保存"
        cancelText="取消"
      >
        <TextArea
          value={editCardModal.value}
          onChange={(e) => setEditCardModal((m) => ({ ...m, value: e.target.value }))}
          rows={4}
          placeholder="修改卡片笔记内容..."
          autoFocus
        />
      </Modal>

      {/* 发送到写作：选择写作项目（Q1-1） */}
      <Modal
        title="发送卡片到写作项目"
        open={sendModal.open}
        onOk={confirmSendCard}
        onCancel={() => setSendModal((m) => ({ ...m, open: false }))}
        okText="发送"
        cancelText="取消"
      >
        <Select
          style={{ width: '100%' }}
          placeholder="选择写作项目"
          value={sendProjectId}
          onChange={setSendProjectId}
          options={projects.map((p) => ({ value: p.id, label: p.title || '未命名项目' }))}
        />
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8 }}>
          卡片内容将追加到所选写作项目的末尾，并自动带上 (Author, Year, p. X) 引用锚文本。
        </Typography.Paragraph>
      </Modal>

      {/* 编辑批注评论弹窗（Zotero 式：为高亮/下划线补充理解） */}
      <Modal
        title="编辑批注评论"
        open={commentModal.open}
        onOk={saveComment}
        onCancel={() => setCommentModal((m) => ({ ...m, open: false }))}
        okText="保存评论"
        cancelText="取消"
      >
        <TextArea
          value={commentModal.value}
          onChange={(e) => setCommentModal((m) => ({ ...m, value: e.target.value }))}
          rows={4}
          placeholder="写下你对这段文字的理解、疑问或备注..."
          autoFocus
        />
      </Modal>

      {/* 引文导出弹窗 */}
      <Modal
        title="导出引文"
        open={!!citation}
        onCancel={() => setCitation(null)}
        onOk={downloadCitation}
        okText="下载文件"
        cancelText="关闭"
        width={640}
      >
        {citation && (
          <div>
            <Typography.Text type="secondary" style={{ marginBottom: 8, display: 'block' }}>
              格式：{citation.format}（{citation.filename}）
            </Typography.Text>
            <pre
              style={{
                background: '#f6f8fa',
                padding: 12,
                borderRadius: 6,
                maxHeight: 320,
                overflow: 'auto',
                fontSize: 12,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
              }}
            >
              {citation.citation}
            </pre>
            <Button
              type="primary"
              size="small"
              style={{ marginTop: 8 }}
              onClick={() => {
                navigator.clipboard.writeText(citation.citation)
                message.success('已复制到剪贴板')
              }}
            >
              复制文本
            </Button>
          </div>
        )}
      </Modal>

    </div>
  )
}
