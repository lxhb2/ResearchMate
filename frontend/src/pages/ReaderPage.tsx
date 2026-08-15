import { useEffect, useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
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
} from 'antd'
import { ArrowLeftOutlined, SendOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { Document, Page, pdfjs } from 'react-pdf'
import ReactMarkdown from 'react-markdown'
// react-pdf 文字层/批注层样式：必须导入，否则文字层不会绝对定位铺在 canvas 上，
// 会导致"选中文字与原 PDF 错层"（内容被排成上下两段、无法在原位选中）。
import 'react-pdf/dist/Page/TextLayer.css'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import type { Paper, Annotation } from '../types'
import { papersApi, type PaperAnalysis } from '../api/papers'
import { annotationsApi, translateApi, termApi } from '../api/search'
import { api, getErrorMessage } from '../api/client'

// 配置 pdf.js worker：用 Vite 打包本地 worker，离线环境也能渲染 PDF
pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()

const { TextArea } = Input

interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
}

const annotationTypeLabel: Record<string, string> = {
  highlight: '高亮',
  underline: '下划线',
  note: '笔记',
  summary: '总结',
}

export default function ReaderPage() {
  const { paperId } = useParams<{ paperId: string }>()
  const navigate = useNavigate()
  const [paper, setPaper] = useState<Paper | null>(null)
  const [numPages, setNumPages] = useState(0)
  const [pageNumber, setPageNumber] = useState(1)
  const [loading, setLoading] = useState(true)
  const [pdfSrc, setPdfSrc] = useState<string | null>(null)

  const [annotations, setAnnotations] = useState<Annotation[]>([])
  const [chatMessages, setChatMessages] = useState<ChatMsg[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [summary, setSummary] = useState('')
  const [summaryLoading, setSummaryLoading] = useState(false)
  const [tab, setTab] = useState('analysis')

  const [analysis, setAnalysis] = useState<PaperAnalysis | null>(null)
  const [analysisLoading, setAnalysisLoading] = useState(false)

  const [selection, setSelection] = useState<{ text: string; x: number; y: number } | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!paperId) return
    setLoading(true)
    papersApi
      .get(paperId)
      .then((p) => setPaper(p))
      .catch((err) => message.error(getErrorMessage(err)))
      .finally(() => setLoading(false))
    annotationsApi
      .list(paperId)
      .then(setAnnotations)
      .catch((err) => message.error(getErrorMessage(err)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paperId])

  // 用带鉴权的请求获取 PDF 文件，转成 blob URL 供 react-pdf 渲染（文件接口需要登录）
  useEffect(() => {
    if (!paperId) return
    let url: string | null = null
    api
      .get(`/papers/${paperId}/file`, { responseType: 'blob' })
      .then(({ data }) => {
        url = URL.createObjectURL(data)
        setPdfSrc(url)
      })
      .catch((err) => message.error(getErrorMessage(err)))
    return () => {
      if (url) URL.revokeObjectURL(url)
    }
  }, [paperId])

  const onMouseUp = () => {
    const sel = window.getSelection()
    const text = sel?.toString().trim()
    if (text && text.length > 1 && containerRef.current) {
      const rect = sel!.getRangeAt(0).getBoundingClientRect()
      const containerRect = containerRef.current.getBoundingClientRect()
      setSelection({
        text,
        x: rect.left - containerRect.left + rect.width / 2,
        y: rect.top - containerRect.top - 10,
      })
    } else {
      setSelection(null)
    }
  }

  const addAnnotation = async (type: Annotation['type']) => {
    if (!paperId) return
    try {
      const ann = await annotationsApi.create({
        paper_id: paperId,
        type,
        content: selection?.text ?? null,
        page_number: pageNumber,
        position: null,
      })
      setAnnotations((prev) => [ann, ...prev])
      message.success('已保存批注')
    } catch (err) {
      message.error(getErrorMessage(err))
    }
    setSelection(null)
    window.getSelection()?.removeAllRanges()
  }

  const handleTranslate = async () => {
    if (!selection) return
    const text = selection.text
    setSelection(null)
    window.getSelection()?.removeAllRanges()
    try {
      const { translation } = await translateApi.translate(text, 'zh')
      Modal.info({
        title: '中文翻译',
        content: <div style={{ whiteSpace: 'pre-wrap' }}>{translation}</div>,
        width: 520,
        okText: '关闭',
      })
    } catch (err) {
      message.error(getErrorMessage(err))
    }
  }

  const handleExplain = async () => {
    if (!selection) return
    const text = selection.text
    setSelection(null)
    window.getSelection()?.removeAllRanges()
    setTab('ai')
    setChatMessages((prev) => [...prev, { role: 'user', content: `解释术语："${text}"` }])
    setChatLoading(true)
    try {
      const { explanation } = await termApi.lookup(text, false)
      setChatMessages((prev) => [...prev, { role: 'assistant', content: explanation }])
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setChatLoading(false)
    }
  }

  const sendChat = async () => {
    if (!paperId || !chatInput.trim()) return
    const msg = chatInput.trim()
    setChatInput('')
    setChatMessages((prev) => [...prev, { role: 'user', content: msg }])
    setChatLoading(true)
    try {
      const { answer } = await papersApi.chat(paperId, msg)
      setChatMessages((prev) => [...prev, { role: 'assistant', content: answer }])
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setChatLoading(false)
    }
  }

  const generateSummary = async () => {
    if (!paperId) return
    setSummaryLoading(true)
    try {
      const { summary: s } = await papersApi.summary(paperId, 'full')
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

  // 首次进入「论文分析」标签时自动加载
  useEffect(() => {
    if (tab === 'analysis' && !analysis && !analysisLoading) {
      loadAnalysis()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

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
    return (
      <div style={{ maxHeight: 560, overflow: 'auto', paddingRight: 8 }}>
        <Typography.Title level={5}>AI 语义分析</Typography.Title>
        {dims.length === 0 ? (
          <Typography.Text type="secondary">该论文尚未完成维度拆分（状态：{analysis.status}）。</Typography.Text>
        ) : (
          dims.map((d) => (
            <div key={d.dimension} style={{ marginBottom: 16 }}>
              <Tag color="blue">{d.label}</Tag>
              <div style={{ whiteSpace: 'pre-wrap', marginTop: 4, fontSize: 13 }}>
                {d.content}
              </div>
            </div>
          ))
        )}

        <Divider />
        <Typography.Title level={5}>
          我的笔记（{analysis.user_notes.length}）
        </Typography.Title>
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
            <Button onClick={() => setPageNumber((p) => Math.max(1, p - 1))} disabled={pageNumber <= 1}>
              上一页
            </Button>
            <span>
              {pageNumber} / {numPages || '?'}
            </span>
            <Button onClick={() => setPageNumber((p) => Math.min(numPages, p + 1))} disabled={pageNumber >= numPages}>
              下一页
            </Button>
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
              >
                <Page
                  pageNumber={pageNumber}
                  renderTextLayer
                  renderAnnotationLayer
                  width={Math.min(700, (containerRef.current?.clientWidth || 700) - 32)}
                />
              </Document>
            )}

            {selection && (
              <div
                style={{
                  position: 'absolute',
                  left: Math.max(20, Math.min(selection.x - 100, (containerRef.current?.clientWidth || 700) - 220)),
                  top: selection.y,
                  zIndex: 10,
                }}
              >
                <Space style={{ background: '#fff', padding: '4px 8px', borderRadius: 6, boxShadow: '0 2px 8px rgba(0,0,0,0.2)' }}>
                  <Button size="small" onClick={handleTranslate}>翻译</Button>
                  <Button size="small" onClick={handleExplain}>解释</Button>
                  <Button size="small" onClick={() => addAnnotation('highlight')}>高亮</Button>
                  <Button size="small" onClick={() => addAnnotation('note')}>笔记</Button>
                </Space>
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
                label: '批注',
                children: (
                  <List
                    dataSource={annotations}
                    locale={{ emptyText: <Empty description="还没有批注" /> }}
                    renderItem={(ann) => (
                      <List.Item
                        actions={[
                          <a
                            key="del"
                            onClick={async () => {
                              if (ann.id) {
                                await annotationsApi.remove(ann.id)
                                setAnnotations((prev) => prev.filter((a) => a.id !== ann.id))
                              }
                            }}
                          >
                            删除
                          </a>,
                        ]}
                      >
                        <List.Item.Meta
                          title={
                            <Space>
                              <Tag>{annotationTypeLabel[ann.type] || ann.type}</Tag>
                              <span>第 {ann.page_number ?? '-'} 页</span>
                            </Space>
                          }
                          description={ann.content || '（空）'}
                        />
                      </List.Item>
                    )}
                  />
                ),
              },
              {
                key: 'ai',
                label: 'AI 助手',
                children: (
                  <div style={{ display: 'flex', flexDirection: 'column', height: 520 }}>
                    <div style={{ flex: 1, overflow: 'auto', paddingRight: 8 }}>
                      {chatMessages.length === 0 && (
                        <Typography.Text type="secondary">
                          可以就这篇论文提问，例如「它的主要贡献是什么？」
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
                            <ReactMarkdown>{m.content}</ReactMarkdown>
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
                      <Button icon={<ThunderboltOutlined />} onClick={generateSummary}>
                        生成全文总结
                      </Button>
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
    </div>
  )
}
