import { useEffect, useRef, useState } from 'react'
import { Modal, Input, Select, Checkbox, Button, Spin, Typography, message, Empty, Tag, Space } from 'antd'
import { FileSearchOutlined, StopOutlined, InsertRowAboveOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import { papersApi, type LitReviewOptions, type ReviewCitation } from '../api/papers'
import type { Paper } from '../types'
import { getErrorMessage } from '../api/client'

const { TextArea } = Input

const STRUCTURE_OPTIONS = [
  { value: 'thematic', label: '主题式（按主题分组）' },
  { value: 'chronological', label: '时间线式（按时间脉络）' },
  { value: 'gap_analysis', label: '研究空白分析式' },
]

const STYLE_OPTIONS = [
  { value: 'apa', label: 'APA（作者-年份）' },
  { value: 'gb7714', label: 'GB/T 7714（国标）' },
  { value: 'bibtex_citekey', label: 'BibTeX cite key' },
]

interface LitReviewModalProps {
  open: boolean
  onClose: () => void
  /** 生成完成后，把综述正文作为正式内容块插入写作文档 */
  onInsert: (text: string, citations: ReviewCitation[]) => void
}

export default function LitReviewModal({ open, onClose, onInsert }: LitReviewModalProps) {
  const [papers, setPapers] = useState<Paper[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [topic, setTopic] = useState('')
  const [structure, setStructure] = useState<LitReviewOptions['structure']>('thematic')
  const [citationStyle, setCitationStyle] = useState<LitReviewOptions['citation_style']>('apa')
  const [streaming, setStreaming] = useState(false)
  const [output, setOutput] = useState('')
  const [citations, setCitations] = useState<ReviewCitation[]>([])
  const [done, setDone] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const loadPapers = async () => {
    try {
      const res = await papersApi.list({ limit: 200 })
      setPapers(res.items.filter((p) => p.status !== 'processing' && p.status !== 'error'))
    } catch (err) {
      message.error(getErrorMessage(err))
    }
  }

  useEffect(() => {
    if (open) {
      loadPapers()
      setSelectedIds(new Set())
      setTopic('')
      setOutput('')
      setCitations([])
      setDone(false)
    }
  }, [open])

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const start = async () => {
    const t = topic.trim()
    if (!t) {
      message.warning('请填写综述主题')
      return
    }
    if (selectedIds.size === 0) {
      message.warning('请先勾选要纳入综述的文献')
      return
    }
    setOutput('')
    setCitations([])
    setDone(false)
    setStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      await papersApi.literatureReview(
        {
          paper_ids: [...selectedIds],
          topic: t,
          structure,
          citation_style: citationStyle,
        },
        (delta) => setOutput((prev) => prev + delta),
        (cits) => setCitations(cits),
        () => setDone(true),
        controller.signal,
      )
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        setDone(true)
      } else {
        message.error(getErrorMessage(err))
        setDone(true)
      }
    } finally {
      setStreaming(false)
      abortRef.current = null
    }
  }

  const stop = () => {
    abortRef.current?.abort()
  }

  return (
    <Modal
      title="生成综述段落并插入文档"
      open={open}
      onCancel={onClose}
      width={760}
      footer={
        <Space>
          <Button onClick={onClose}>关闭</Button>
          {done && output.trim() && (
            <Button type="primary" icon={<InsertRowAboveOutlined />} onClick={() => onInsert(output, citations)}>
              插入到文档
            </Button>
          )}
          {!streaming ? (
            <Button type="primary" icon={<FileSearchOutlined />} onClick={start} disabled={papers.length === 0}>
              生成综述
            </Button>
          ) : (
            <Button danger icon={<StopOutlined />} onClick={stop}>
              停止
            </Button>
          )}
        </Space>
      }
    >
      <div style={{ marginBottom: 8 }}>
        <Typography.Text strong>① 选择文献（{selectedIds.size} 篇）</Typography.Text>
      </div>
      <div style={{ maxHeight: 150, overflow: 'auto', border: '1px solid #eee', borderRadius: 8, padding: 8 }}>
        {papers.length === 0 ? (
          <Empty description="暂无可用文献，请先到「文献库」上传并解析" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          papers.map((p) => (
            <Checkbox key={p.id} checked={selectedIds.has(p.id)} onChange={() => toggleSelect(p.id)} style={{ display: 'flex', marginBottom: 4 }}>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 560 }}>
                {p.title || '未命名'}
                {p.year ? `（${p.year}）` : ''}
              </span>
            </Checkbox>
          ))
        )}
      </div>

      <div style={{ marginTop: 12, marginBottom: 8 }}>
        <Typography.Text strong>② 综述主题</Typography.Text>
      </div>
      <TextArea
        rows={2}
        placeholder="例如：大语言模型在科研文献综述中的应用现状与挑战"
        value={topic}
        onChange={(e) => setTopic(e.target.value)}
      />

      <div style={{ display: 'flex', gap: 12, marginTop: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ marginBottom: 4 }}>组织结构</div>
          <Select style={{ width: '100%' }} value={structure} onChange={setStructure} options={STRUCTURE_OPTIONS} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ marginBottom: 4 }}>引用样式</div>
          <Select style={{ width: '100%' }} value={citationStyle} onChange={setCitationStyle} options={STYLE_OPTIONS} />
        </div>
      </div>

      {(streaming || output.trim() || done) && (
        <div style={{ marginTop: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <Typography.Text strong>③ 生成结果</Typography.Text>
            {streaming && <Spin size="small" />}
            {done && <Tag color="green">已完成</Tag>}
          </div>
          <div
            className="markdown-body"
            style={{
              maxHeight: 240,
              overflow: 'auto',
              background: '#fafafa',
              border: '1px solid #eee',
              borderRadius: 8,
              padding: 12,
              fontSize: 13,
            }}
          >
            <ReactMarkdown>{output || '*正在生成…*'}</ReactMarkdown>
          </div>
          {citations.length > 0 && (
            <div style={{ marginTop: 8, padding: '6px 8px', background: '#eef0ff', borderRadius: 6, fontSize: 12 }}>
              <div style={{ color: '#4f46e5', fontWeight: 600, marginBottom: 4 }}>
                引用来源（{citations.length}）
              </div>
              {citations.map((c, ci) => (
                <div key={ci} style={{ display: 'flex', gap: 6, marginBottom: 4, alignItems: 'flex-start' }}>
                  <Tag color="geekblue" style={{ margin: 0, flexShrink: 0 }}>
                    {c.citation}
                  </Tag>
                  <span style={{ fontSize: 12, color: '#555', lineHeight: 1.5 }}>
                    {c.paper_title}
                    {c.page ? ` · p.${c.page}` : ''}
                    <span style={{ color: '#999' }}> · {c.snippet}</span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}
