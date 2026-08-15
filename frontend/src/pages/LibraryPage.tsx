import { useEffect, useState } from 'react'
import {
  Card,
  Row,
  Col,
  Input,
  Button,
  Upload,
  Tag,
  Empty,
  Spin,
  message,
  Typography,
  Modal,
} from 'antd'
import { InboxOutlined, DeleteOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { Paper } from '../types'
import { papersApi } from '../api/papers'
import { searchApi } from '../api/search'
import { getErrorMessage } from '../api/client'

const { Dragger } = Upload

const statusLabel: Record<string, string> = {
  processing: '处理中',
  ready: '就绪',
  completed: '就绪',
  error: '出错',
}
const statusColor: Record<string, string> = {
  processing: 'processing',
  ready: 'success',
  completed: 'success',
  error: 'error',
}

export default function LibraryPage() {
  const navigate = useNavigate()
  const [papers, setPapers] = useState<Paper[]>([])
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [semanticQuery, setSemanticQuery] = useState('')
  const [semanticResults, setSemanticResults] = useState<Paper[] | null>(null)
  const [uploading, setUploading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const res = await papersApi.list({ search, limit: 100 })
      setPapers(res.items)
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search])

  // 有文献正在处理时轮询
  useEffect(() => {
    const hasProcessing = papers.some((p) => p.status === 'processing')
    if (!hasProcessing) return
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [papers.some((p) => p.status === 'processing')])

  const handleUpload = async (file: File) => {
    setUploading(true)
    try {
      await papersApi.upload(file)
      message.success('已开始上传，正在后台解析')
      load()
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setUploading(false)
    }
    return false // 阻止默认上传行为
  }

  const handleDelete = (paper: Paper) => {
    Modal.confirm({
      title: '删除文献？',
      content: `《${paper.title}》将被永久删除。`,
      okText: '删除',
      cancelText: '取消',
      okType: 'danger',
      onOk: async () => {
        try {
          await papersApi.remove(paper.id)
          message.success('已删除')
          load()
        } catch (err) {
          message.error(getErrorMessage(err))
        }
      },
    })
  }

  const handleSemantic = async () => {
    if (!semanticQuery.trim()) return
    setLoading(true)
    try {
      const res = await searchApi.semantic(semanticQuery, 8)
      const seen = new Set<string>()
      const matched: Paper[] = []
      for (const item of res.items) {
        if (seen.has(item.paper_id)) continue
        seen.add(item.paper_id)
        const p = papers.find((x) => x.id === item.paper_id)
        if (p) matched.push(p)
      }
      setSemanticResults(matched.length ? matched : [])
      if (!matched.length) message.info('文库中没有匹配项')
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const displayed = semanticResults ?? papers

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col flex="auto">
          <Input
            placeholder="按标题搜索..."
            prefix={<SearchOutlined />}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            allowClear
          />
        </Col>
        <Col>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col flex="auto">
          <Input
            placeholder="在整个文库中进行语义检索..."
            value={semanticQuery}
            onChange={(e) => setSemanticQuery(e.target.value)}
            onPressEnter={handleSemantic}
            allowClear
          />
        </Col>
        <Col>
          <Button type="primary" onClick={handleSemantic}>
            语义检索
          </Button>
          {semanticResults && (
            <Button
              style={{ marginLeft: 8 }}
              onClick={() => {
                setSemanticResults(null)
                setSemanticQuery('')
              }}
            >
              清除
            </Button>
          )}
        </Col>
      </Row>

      <Dragger
        accept=".pdf"
        multiple={false}
        showUploadList={false}
        beforeUpload={handleUpload}
        disabled={uploading}
        style={{ marginBottom: 24, background: '#fafafa' }}
      >
        {uploading ? (
          <Spin tip="正在上传..." />
        ) : (
          <>
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">点击或将 PDF 拖拽到此处上传</p>
            <p className="ant-upload-hint">PDF 将被自动解析并完成向量化存储</p>
          </>
        )}
      </Dragger>

      {loading && !papers.length ? (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin />
        </div>
      ) : displayed.length === 0 ? (
        <Empty description="还没有文献，上传一篇 PDF 开始吧。" />
      ) : (
        <Row gutter={[16, 16]}>
          {displayed.map((paper) => (
            <Col xs={24} sm={12} lg={8} xl={6} key={paper.id}>
              <Card
                hoverable
                onClick={() => ['ready', 'completed'].includes(paper.status) && navigate(`/reader/${paper.id}`)}
                actions={[
                  <DeleteOutlined key="delete" onClick={(e) => { e.stopPropagation(); handleDelete(paper) }} />,
                ]}
              >
                <Card.Meta
                  title={
                    <Typography.Text ellipsis style={{ maxWidth: '100%' }}>
                      {paper.title || '未命名'}
                    </Typography.Text>
                  }
                  description={
                    <>
                      <div style={{ height: 40, overflow: 'hidden' }}>
                        {(paper.authors || []).slice(0, 3).join('、')}
                        {paper.authors && paper.authors.length > 3 ? ' 等' : ''}
                      </div>
                      <div style={{ marginTop: 8 }}>
                        {paper.year && <Tag>{paper.year}</Tag>}
                        <Tag color={statusColor[paper.status]}>
                          {paper.status === 'processing' ? <Spin size="small" /> : statusLabel[paper.status]}
                        </Tag>
                      </div>
                    </>
                  }
                />
              </Card>
            </Col>
          ))}
        </Row>
      )}
    </div>
  )
}
