import { useEffect, useMemo, useRef, useState } from 'react'
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
  Select,
  Space,
  Checkbox,
  Alert,
  Tabs,
  Dropdown,
  List,
} from 'antd'
import {
  InboxOutlined,
  DeleteOutlined,
  ReloadOutlined,
  SearchOutlined,
  TagsOutlined,
  LoadingOutlined,
  ImportOutlined,
  DownloadOutlined,
  FileSearchOutlined,
  ReadOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { Paper } from '../types'
import { papersApi } from '../api/papers'
import { searchApi } from '../api/search'
import { importsApi, type ImportPreview, type ImportResult } from '../api/imports'
import { getErrorMessage } from '../api/client'
import { useUiStateStore } from '../store/uiStateStore'

const { Dragger } = Upload

export default function LibraryPage() {
  const navigate = useNavigate()
  const reader = useUiStateStore((s) => s.reader)
  const pdfTask = useUiStateStore((s) => s.pdfTask)
  const [papers, setPapers] = useState<Paper[]>([])
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [semanticQuery, setSemanticQuery] = useState('')
  const [semanticResults, setSemanticResults] = useState<Paper[] | null>(null)
  const [uploading, setUploading] = useState(false)
  // 标签筛选（Zotero 式：按标签过滤文献库）
  const [tagFilter, setTagFilter] = useState<string | undefined>(undefined)
  const [allTags, setAllTags] = useState<{ name: string; count: number }[]>([])
  // 标签编辑弹窗
  const [tagModal, setTagModal] = useState<{ open: boolean; paper?: Paper; value: string[] }>({
    open: false,
    value: [],
  })
  // 文献导入弹窗（Zotero / BibTeX / RIS）
  const [importModal, setImportModal] = useState<{ open: boolean; source: 'zotero' | 'bibtex' | 'ris' }>({
    open: false,
    source: 'zotero',
  })
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null)
  const [importResult, setImportResult] = useState<ImportResult | null>(null)
  const [importLoading, setImportLoading] = useState(false)
  const [zoteroDir, setZoteroDir] = useState('')
  const [bibtexText, setBibtexText] = useState('')
  const [risText, setRisText] = useState('')
  // 批量导出：勾选文献
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [bulkDeleting, setBulkDeleting] = useState(false)
  // 生成综述弹窗（Q1-2）：题目 / 结构 / 引用样式 → 跳转 ChatPage 流式生成
  const [reviewModal, setReviewModal] = useState<{
    open: boolean
    topic: string
    structure: 'thematic' | 'chronological' | 'gap_analysis'
    citation_style: 'apa' | 'gb7714' | 'bibtex_citekey'
  }>({ open: false, topic: '', structure: 'thematic', citation_style: 'apa' })

  const load = async () => {
    setLoading(true)
    try {
      const res = await papersApi.list({ search, tag: tagFilter, limit: 100 })
      setPapers(res.items)
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const loadTags = async () => {
    try {
      const res = await papersApi.tags()
      setAllTags(res.tags)
    } catch {
      /* 标签加载失败不阻塞 */
    }
  }

  useEffect(() => {
    load()
    loadTags()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, tagFilter])

  useEffect(() => {
    if (tagModal.open) return
    loadTags()
  }, [tagModal.open])

  // 有文献正在本地解析或 AI 分析中时轮询（AI 分析在后台慢慢跑，不阻塞阅读）
  const anyBusy = papers.some(
    (p) => p.status === 'processing' || (p.status !== 'error' && p.analysis_status === 'pending'),
  )
  useEffect(() => {
    if (!anyBusy) return
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anyBusy])

  // 批量上传队列：antd 对每个选中文件调用 beforeUpload，这里入队后串行上传，
  // 避免并发上传时 uploading 状态与提示混乱（Zotero 式批量导入体验）。
  const uploadQueue = useRef<File[]>([])
  const pumping = useRef(false)

  const pumpQueue = async () => {
    if (pumping.current) return
    pumping.current = true
    setUploading(true)
    while (uploadQueue.current.length) {
      const file = uploadQueue.current.shift()!
      try {
        await papersApi.upload(file)
        message.success(`《${file.name}》已上传，可直接点击打开阅读`)
      } catch (err) {
        message.error(`${file.name}：${getErrorMessage(err)}`)
      }
    }
    pumping.current = false
    setUploading(false)
    load()
  }

  const handleUpload = (file: File) => {
    uploadQueue.current.push(file)
    pumpQueue()
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
  const displayedIds = useMemo(() => displayed.map((paper) => paper.id), [displayed])
  const displayedIdsKey = displayedIds.join('\n')
  const selectedDisplayedIds = useMemo(
    () => displayedIds.filter((id) => selectedIds.has(id)),
    [displayedIds, selectedIds],
  )
  const allDisplayedSelected = displayedIds.length > 0 && selectedDisplayedIds.length === displayedIds.length

  // 搜索、标签筛选或语义检索变化后，不让不可见的旧选择参与删除。
  useEffect(() => {
    const visible = new Set(displayedIdsKey ? displayedIdsKey.split('\n') : [])
    setSelectedIds((prev) => {
      const next = new Set([...prev].filter((id) => visible.has(id)))
      return next.size === prev.size ? prev : next
    })
  }, [displayedIdsKey])

  const saveTags = async () => {
    const { paper, value } = tagModal
    if (!paper) return
    setTagModal((m) => ({ ...m, open: false }))
    try {
      await papersApi.update(paper.id, { tags: value })
      message.success('已更新标签')
      load()
    } catch (err) {
      message.error(getErrorMessage(err))
    }
  }

  // ---- 导入：预览（只解析不回写）→ 确认导入 ----
  const runImportPreview = async () => {
    setImportPreview(null)
    setImportResult(null)
    if (importModal.source === 'zotero' && !zoteroDir.trim()) {
      message.warning('请输入 Zotero 数据目录（含 zotero.sqlite 的目录）')
      return
    }
    if (importModal.source === 'bibtex' && !bibtexText.trim()) {
      message.warning('请粘贴 BibTeX 内容')
      return
    }
    if (importModal.source === 'ris' && !risText.trim()) {
      message.warning('请粘贴 RIS 内容')
      return
    }
    setImportLoading(true)
    try {
      let res: ImportPreview
      if (importModal.source === 'zotero') res = await importsApi.zoteroPreview(zoteroDir.trim())
      else if (importModal.source === 'bibtex') res = await importsApi.bibtexPreview(bibtexText)
      else res = await importsApi.risPreview(risText)
      if (!res.ok && res.errors.length) message.error(res.errors[0])
      setImportPreview(res)
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setImportLoading(false)
    }
  }

  const runImport = async () => {
    if (!importPreview || !importPreview.ok) {
      message.warning('请先点击「预览」确认命中情况')
      return
    }
    setImportLoading(true)
    try {
      let res: ImportResult
      if (importModal.source === 'zotero') res = await importsApi.zoteroImport(zoteroDir.trim())
      else if (importModal.source === 'bibtex') res = await importsApi.bibtexImport(bibtexText)
      else res = await importsApi.risImport(risText)
      setImportResult(res)
      message.success(`成功导入 ${res.count} 篇（含 PDF ${res.with_pdf} 篇，跳过重复 ${res.skipped_duplicates} 篇）`)
      load()
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setImportLoading(false)
    }
  }

  // ---- 批量导出 ----
  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSelectAll = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (allDisplayedSelected) {
        displayedIds.forEach((id) => next.delete(id))
      } else {
        displayedIds.forEach((id) => next.add(id))
      }
      return next
    })
  }

  const handleBulkDelete = () => {
    const ids = [...selectedDisplayedIds]
    if (!ids.length) {
      message.warning('请先勾选要删除的文献')
      return
    }
    Modal.confirm({
      title: '批量删除文献？',
      content: `当前结果中的 ${ids.length} 篇论文及其 PDF、标注和对话记录将被永久删除。`,
      okText: '全部删除',
      cancelText: '取消',
      okType: 'danger',
      onOk: async () => {
        setBulkDeleting(true)
        try {
          const res = await papersApi.bulkRemove(ids)
          message.success(`已删除 ${res.deleted} 篇论文`)
          setSelectedIds((prev) => new Set([...prev].filter((id) => !ids.includes(id))))
          await load()
        } catch (err) {
          message.error(getErrorMessage(err))
        } finally {
          setBulkDeleting(false)
        }
      },
    })
  }

  const downloadExport = (fmt: 'bibtex' | 'ris') => {
    const ids = [...selectedIds]
    if (!ids.length) {
      message.warning('请先勾选要导出的文献')
      return
    }
    papersApi
      .exportPapers(ids, fmt)
      .then((res) => {
        const blob = new Blob([res.content], { type: 'text/plain;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = res.filename
        a.click()
        URL.revokeObjectURL(url)
        message.success(`已导出 ${res.count} 篇为 ${fmt.toUpperCase()}`)
      })
      .catch((err) => message.error(getErrorMessage(err)))
  }

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
          <Select
            placeholder="按标签筛选"
            allowClear
            style={{ minWidth: 160 }}
            value={tagFilter}
            onChange={setTagFilter}
            options={allTags.map((t) => ({ value: t.name, label: `${t.name} (${t.count})` }))}
          />
        </Col>
        <Col>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
        </Col>
        <Col>
          <Dropdown
            menu={{
              items: [
                { key: 'zotero', label: '从 Zotero 导入' },
                { key: 'bibtex', label: '从 BibTeX 导入' },
                { key: 'ris', label: '从 RIS 导入' },
                { type: 'divider' },
                { key: 'export-bibtex', label: '导出所选为 BibTeX' },
                { key: 'export-ris', label: '导出所选为 RIS' },
              ],
              onClick: ({ key }) => {
                if (key === 'zotero' || key === 'bibtex' || key === 'ris') {
                  setImportPreview(null)
                  setImportResult(null)
                  setImportModal({ open: true, source: key })
                } else if (key === 'export-bibtex') {
                  downloadExport('bibtex')
                } else if (key === 'export-ris') {
                  downloadExport('ris')
                }
              },
            }}
          >
            <Button type="primary" icon={<ImportOutlined />}>
              导入 / 导出
            </Button>
          </Dropdown>
        </Col>
      </Row>

      {reader && (
        <Alert
          type="info"
          showIcon
          icon={<ReadOutlined />}
          style={{ marginBottom: 16 }}
          message={`继续阅读上次论文：${reader.title || '未命名'}`}
          description={
            pdfTask?.paperId === reader.paperId
              ? `整篇翻译进行中（${Math.round(pdfTask.progress || 0)}%）· 上次位置第 ${reader.page || 1} 页`
              : `上次位置：第 ${reader.page || 1} 页`
          }
          action={
            <Button type="primary" size="small" onClick={() => navigate(`/reader/${reader.paperId}?page=${reader.page || 1}`)}>
              继续阅读
            </Button>
          }
        />
      )}

      {selectedIds.size > 0 && (
        <Row gutter={16} style={{ marginBottom: 16 }} align="middle">
          <Col flex="auto">
            <Typography.Text type="secondary">
              已选中 <b>{selectedIds.size}</b> 篇文献
            </Typography.Text>
          </Col>
          <Col>
            <Space>
              <Button type="primary" icon={<FileSearchOutlined />} onClick={() => setReviewModal((m) => ({ ...m, open: true }))}>
                生成综述…
              </Button>
              <Button icon={<DownloadOutlined />} onClick={() => downloadExport('bibtex')}>
                导出 BibTeX
              </Button>
              <Button icon={<DownloadOutlined />} onClick={() => downloadExport('ris')}>
                导出 RIS
              </Button>
              <Button onClick={() => setSelectedIds(new Set())}>取消选择</Button>
            </Space>
          </Col>
        </Row>
      )}

      {displayed.length > 0 && (
        <Row gutter={16} style={{ marginBottom: 16 }} align="middle">
          <Col flex="auto">
            <Checkbox
              checked={allDisplayedSelected}
              indeterminate={selectedDisplayedIds.length > 0 && !allDisplayedSelected}
              onChange={toggleSelectAll}
              disabled={bulkDeleting}
            >
              全选当前结果（{displayedIds.length} 篇）
            </Checkbox>
          </Col>
          <Col>
            <Button
              danger
              icon={<DeleteOutlined />}
              loading={bulkDeleting}
              disabled={!selectedDisplayedIds.length}
              onClick={handleBulkDelete}
            >
              删除所选（{selectedDisplayedIds.length}）
            </Button>
          </Col>
        </Row>
      )}

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
        multiple
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
            <p className="ant-upload-text">点击或将 PDF 拖拽到此处上传（支持批量）</p>
            <p className="ant-upload-hint">上传后立即可打开阅读；AI 语义解析在后台自动进行</p>
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
                style={{ position: 'relative' }}
                // PDF 文件在上传接口返回时已落盘，任何状态都可立即点开阅读
                // （AI 分析/标签在后台慢慢补齐，不阻塞阅读）
                onClick={() => navigate(`/reader/${paper.id}`)}
                actions={[
                  <TagsOutlined
                    key="tags"
                    onClick={(e) => {
                      e.stopPropagation()
                      setTagModal({ open: true, paper, value: paper.tags ?? [] })
                    }}
                  />,
                  <DeleteOutlined key="delete" onClick={(e) => { e.stopPropagation(); handleDelete(paper) }} />,
                ]}
              >
                {/* 勾选用于批量导出 */}
                <Checkbox
                  style={{ position: 'absolute', top: 8, right: 8, zIndex: 2 }}
                  checked={selectedIds.has(paper.id)}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => toggleSelect(paper.id)}
                />
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
                        {paper.status === 'processing' ? (
                          <Tag color="processing" icon={<LoadingOutlined spin />}>解析中</Tag>
                        ) : paper.status === 'error' ? (
                          <Tag color="error">无法提取文本</Tag>
                        ) : paper.analysis_status === 'pending' ? (
                          <Tag color="processing" icon={<LoadingOutlined spin />}>AI 分析中</Tag>
                        ) : paper.analysis_status === 'failed' ? (
                          <Tag color="warning">AI 分析失败</Tag>
                        ) : (
                          <Tag color="success">就绪</Tag>
                        )}
                      </div>
                      {paper.tags && paper.tags.length > 0 && (
                        <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                          {paper.tags.map((t) => (
                            <Tag key={t} color="blue" style={{ marginInlineEnd: 0 }}>
                              {t}
                            </Tag>
                          ))}
                        </div>
                      )}
                    </>
                  }
                />
              </Card>
            </Col>
          ))}
        </Row>
      )}

      {/* 标签编辑弹窗 */}
      <Modal
        title={tagModal.paper ? `编辑标签：${tagModal.paper.title}` : '编辑标签'}
        open={tagModal.open}
        onOk={saveTags}
        onCancel={() => setTagModal((m) => ({ ...m, open: false }))}
        okText="保存"
        cancelText="取消"
      >
        <Select
          mode="tags"
          style={{ width: '100%' }}
          placeholder="输入标签后回车添加"
          value={tagModal.value}
          onChange={(v) => setTagModal((m) => ({ ...m, value: v }))}
          options={allTags.map((t) => ({ value: t.name, label: t.name }))}
          maxTagCount={8}
          autoFocus
        />
      </Modal>

      {/* 文献导入弹窗（Zotero / BibTeX / RIS：预览 → 确认导入） */}
      <Modal
        title="导入文献"
        open={importModal.open}
        onCancel={() => setImportModal((m) => ({ ...m, open: false }))}
        footer={[
          <Button key="cancel" onClick={() => setImportModal((m) => ({ ...m, open: false }))}>
            关闭
          </Button>,
          <Button key="preview" onClick={runImportPreview} loading={importLoading}>
            预览
          </Button>,
          <Button
            key="import"
            type="primary"
            onClick={runImport}
            loading={importLoading}
            disabled={!importPreview?.ok}
          >
            确认导入
          </Button>,
        ]}
        width={720}
      >
        <Tabs
          activeKey={importModal.source}
          onChange={(k) => {
            setImportModal((m) => ({ ...m, source: k as 'zotero' | 'bibtex' | 'ris' }))
            setImportPreview(null)
            setImportResult(null)
          }}
          items={[
            {
              key: 'zotero',
              label: 'Zotero 库',
              children: (
                <div>
                  <Typography.Paragraph type="secondary">
                    填入 Zotero 数据目录（含 <code>zotero.sqlite</code> 与 <code>storage/</code> 的目录），
                    将只读解析元数据并把本地 PDF 附件复制入库存档。
                  </Typography.Paragraph>
                  <Input
                    placeholder="例如：C:/Users/you/Zotero 或 /home/you/Zotero"
                    value={zoteroDir}
                    onChange={(e) => setZoteroDir(e.target.value)}
                  />
                </div>
              ),
            },
            {
              key: 'bibtex',
              label: 'BibTeX',
              children: (
                <Input.TextArea
                  rows={8}
                  placeholder={'粘贴 BibTeX 内容，例如：\n@article{key,\n  title = {A Deep Learning Method},\n  author = {John Smith},\n  year = {2023}\n}'}
                  value={bibtexText}
                  onChange={(e) => setBibtexText(e.target.value)}
                />
              ),
            },
            {
              key: 'ris',
              label: 'RIS',
              children: (
                <Input.TextArea
                  rows={8}
                  placeholder={'粘贴 RIS 内容，例如：\nTY  - JOUR\nAU  - John Smith\nTI  - A Study on X\nPY  - 2023\nER  -'}
                  value={risText}
                  onChange={(e) => setRisText(e.target.value)}
                />
              ),
            },
          ]}
        />

        {importResult && (
          <Alert
            style={{ marginTop: 12 }}
            type="success"
            showIcon
            message={`导入完成：${importResult.count} 篇（含 PDF ${importResult.with_pdf} 篇，无 PDF ${importResult.without_pdf} 篇，跳过重复 ${importResult.skipped_duplicates} 篇）`}
          />
        )}

        {!importResult && importPreview && importPreview.ok && (
          <div style={{ marginTop: 12 }}>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 8 }}
              message={`共解析到 ${importPreview.total} 篇，其中含本地 PDF ${importPreview.attachments_found} 篇（预览仅展示前 50 篇）`}
            />
            <List
              size="small"
              bordered
              style={{ maxHeight: 260, overflow: 'auto' }}
              dataSource={importPreview.entries}
              locale={{ emptyText: '未解析到条目，请检查输入内容' }}
              renderItem={(e) => (
                <List.Item>
                  <List.Item.Meta
                    title={
                      <Space size={6} wrap>
                        <span>{e.title}</span>
                        {e.has_pdf && <Tag color="green">PDF</Tag>}
                      </Space>
                    }
                    description={
                      <Space size={6} wrap>
                        <span>{(e.authors || []).join('、') || '佚名'}</span>
                        {e.year && <Tag>{e.year}</Tag>}
                        {e.doi && <Tag color="blue">{e.doi}</Tag>}
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          </div>
        )}

        {!importResult && importPreview && !importPreview.ok && (
          <Alert style={{ marginTop: 12 }} type="error" showIcon message={importPreview.errors[0] || '解析失败'} />
        )}
      </Modal>

      {/* 生成综述弹窗（Q1-2）：配置后跳转 ChatPage 流式生成带精确引用的综述 */}
      <Modal
        title="生成文献综述"
        open={reviewModal.open}
        onCancel={() => setReviewModal((m) => ({ ...m, open: false }))}
        onOk={() => {
          const topic = reviewModal.topic.trim()
          if (!topic) {
            message.warning('请填写综述主题')
            return
          }
          if (selectedIds.size === 0) {
            message.warning('请先勾选要纳入综述的文献')
            return
          }
          const preset = {
            paper_ids: [...selectedIds],
            topic,
            structure: reviewModal.structure,
            citation_style: reviewModal.citation_style,
          }
          sessionStorage.setItem('lit-review-preset', JSON.stringify(preset))
          setReviewModal((m) => ({ ...m, open: false, topic: '' }))
          message.success(`将基于 ${preset.paper_ids.length} 篇文献生成综述`)
          navigate('/chat')
        }}
        okText="生成综述"
        cancelText="取消"
      >
        <Typography.Paragraph type="secondary">
          将基于已选中的 <b>{selectedIds.size}</b> 篇文献，在「AI 对话」中流式生成综述，每条结论都带精确的
          引用（作者-年份-页码）。
        </Typography.Paragraph>
        <div style={{ marginBottom: 12 }}>综述主题</div>
        <Input.TextArea
          rows={3}
          placeholder="例如：大语言模型在科研文献综述中的应用现状与挑战"
          value={reviewModal.topic}
          onChange={(e) => setReviewModal((m) => ({ ...m, topic: e.target.value }))}
        />
        <div style={{ display: 'flex', gap: 12, marginTop: 12 }}>
          <div style={{ flex: 1 }}>
            <div style={{ marginBottom: 4 }}>组织结构</div>
            <Select
              style={{ width: '100%' }}
              value={reviewModal.structure}
              onChange={(v) => setReviewModal((m) => ({ ...m, structure: v }))}
              options={[
                { value: 'thematic', label: '主题式（按主题分组）' },
                { value: 'chronological', label: '时间线式（按时间脉络）' },
                { value: 'gap_analysis', label: '研究空白分析式' },
              ]}
            />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ marginBottom: 4 }}>引用样式</div>
            <Select
              style={{ width: '100%' }}
              value={reviewModal.citation_style}
              onChange={(v) => setReviewModal((m) => ({ ...m, citation_style: v }))}
              options={[
                { value: 'apa', label: 'APA（作者-年份）' },
                { value: 'gb7714', label: 'GB/T 7714（国标）' },
                { value: 'bibtex_citekey', label: 'BibTeX cite key' },
              ]}
            />
          </div>
        </div>
      </Modal>
    </div>
  )
}
