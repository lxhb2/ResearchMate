import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Steps,
  Button,
  Input,
  Card,
  Space,
  message,
  Spin,
  Typography,
  Empty,
  Tag,
  Checkbox,
  Row,
  Col,
  Divider,
  Modal,
  List,
  Segmented,
} from 'antd'
import {
  BulbOutlined,
  SaveOutlined,
  DownloadOutlined,
  PlusOutlined,
  PushpinOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import type { Project, ProjectSection } from '../types'
import { projectsApi } from '../api/projects'
import { annotationsApi, type PinCard } from '../api/search'
import type { ReviewCitation } from '../api/papers'
import LitReviewModal from '../components/LitReviewModal'
import { getErrorMessage } from '../api/client'

const { TextArea } = Input

const STEP_TITLES = ['选题', '大纲', '素材', '草稿', '摘要', '导出']

interface MaterialItem {
  chunk_id: string
  paper_id: string
  paper_title: string | null
  dimension: string
  content: string
  score: number
}

const dimensionLabel: Record<string, string> = {
  title_keywords: '标题与关键词',
  background: '背景',
  method: '方法',
  results: '结果',
  conclusion: '结论',
  contributions: '创新点',
}

export default function WritePage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const [project, setProject] = useState<Project | null>(null)
  const [current, setCurrent] = useState(0)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [lang, setLang] = useState<'zh' | 'en'>('zh')

  // 步骤1
  const [direction, setDirection] = useState('')
  const [titles, setTitles] = useState<string[]>([])

  // 步骤2
  const [sections, setSections] = useState<ProjectSection[]>([])

  // 步骤3
  const [materials, setMaterials] = useState<Record<string, MaterialItem[]>>({})
  const [selectedChunks, setSelectedChunks] = useState<Set<string>>(new Set())

  // 步骤4
  const [draft, setDraft] = useState('')
  // 草稿 TextArea 引用：支持「从卡片笔记插入」在光标处插入（Q1-1）
  const draftRef = useRef<React.ComponentRef<typeof TextArea>>(null)
  // 卡片笔记插入弹窗
  const [pinCards, setPinCards] = useState<PinCard[]>([])
  const [showPinCards, setShowPinCards] = useState(false)
  // 生成综述段落弹窗（Q1-2）
  const [showReviewModal, setShowReviewModal] = useState(false)

  // 步骤5
  const [abstractZh, setAbstractZh] = useState('')
  const [abstractEn, setAbstractEn] = useState('')
  const [keywordsZh, setKeywordsZh] = useState<string[]>([])
  const [keywordsEn, setKeywordsEn] = useState<string[]>([])

  const ensureProject = async (): Promise<Project> => {
    if (project) return project
    const p = await projectsApi.create({ title: direction || '新建项目', content: '' })
    navigate(`/write/${p.id}`, { replace: true })
    setProject(p)
    return p
  }

  const loadProject = async (id: string) => {
    setLoading(true)
    try {
      const p = await projectsApi.get(id)
      setProject(p)
      setCurrent(Math.max(0, Math.min(5, p.step - 1)))
      if (p.outline?.sections) setSections(p.outline.sections)
      if (p.outline?.abstract_zh) setAbstractZh(p.outline.abstract_zh)
      if (p.outline?.abstract_en) setAbstractEn(p.outline.abstract_en)
      if (p.outline?.keywords_zh) setKeywordsZh(p.outline.keywords_zh)
      if (p.outline?.keywords_en) setKeywordsEn(p.outline.keywords_en)
      if (p.content) setDraft(p.content)
      setDirection(p.title || '')
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (projectId) loadProject(projectId)
    else setLoading(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const persist = async (patch: Partial<Project>) => {
    if (!project) return
    try {
      const updated = await projectsApi.update(project.id, patch)
      setProject(updated)
    } catch (err) {
      message.error(getErrorMessage(err))
    }
  }

  const goTo = async (step: number) => {
    setCurrent(step)
    if (project) persist({ step: step + 1 })
  }

  // ---- 步骤1 ----
  const onGenerateTitles = async () => {
    if (!direction.trim()) {
      message.warning('请先填写研究方向')
      return
    }
    setBusy(true)
    try {
      const p = await ensureProject()
      await projectsApi.update(p.id, { title: direction, step: 1 })
      const { titles } = await projectsApi.generateTitle(p.id, direction, lang)
      setTitles(titles)
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const chooseTitle = async (title: string) => {
    await persist({ title })
    setDirection(title)
    message.success('已选定题目')
    await goTo(1)
  }

  // ---- 步骤2 ----
  const onGenerateOutline = async () => {
    if (!project) return
    setBusy(true)
    try {
      const { outline } = await projectsApi.generateOutline(project.id, direction, undefined, lang)
      const outlineObj = outline as { sections: ProjectSection[] }
      const secs = outlineObj.sections
      setSections(secs || [])
      await persist({ outline: { ...(project.outline || {}), sections: secs } })
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const updateSection = (idx: number, field: keyof ProjectSection, value: string) => {
    setSections((prev) => {
      const next = [...prev]
      next[idx] = { ...next[idx], [field]: value }
      return next
    })
  }

  const saveOutline = async () => {
    if (!project) return
    await persist({ outline: { ...(project.outline || {}), sections } })
    message.success('大纲已保存')
  }

  // ---- 步骤3 ----
  const onSearchMaterials = async () => {
    if (!project) return
    setBusy(true)
    try {
      const { materials } = await projectsApi.searchMaterials(
        project.id,
        sections.map((s) => s.title),
        4,
      )
      setMaterials(materials as Record<string, MaterialItem[]>)
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const toggleChunk = (id: string) => {
    setSelectedChunks((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // ---- 步骤4 ----
  const onGenerateDraft = async (sectionTitle?: string) => {
    if (!project) return
    setBusy(true)
    try {
      const { content } = await projectsApi.generateDraft(
        project.id,
        { sections },
        Array.from(selectedChunks),
        sectionTitle,
        lang,
      )
      setDraft(content)
      await persist({ content })
      message.success(sectionTitle ? `已生成：${sectionTitle}` : '草稿已生成')
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const saveDraft = async () => {
    await persist({ content: draft })
    message.success('草稿已保存')
  }

  // ---- 从卡片笔记插入（Q1-1）----
  const openPinCards = async () => {
    try {
      setPinCards(await annotationsApi.listPinCards())
      setShowPinCards(true)
    } catch (err) {
      message.error(getErrorMessage(err))
    }
  }

  // 在草稿光标处插入卡片内容 + 引用锚文本（(Author, Year, p. X)）
  const insertPinCard = (card: PinCard) => {
    const body = (card.note || card.snippet || '').trim()
    const anchor = card.anchor || ''
    const text = `\n\n${body} ${anchor}`
    const ta = draftRef.current?.resizableTextArea?.textArea
    const start = ta?.selectionStart ?? draft.length
    const end = ta?.selectionEnd ?? start
    const next = draft.slice(0, start) + text + draft.slice(end)
    setDraft(next)
    const pos = start + text.length
    requestAnimationFrame(() => {
      ta?.focus()
      try {
        ta?.setSelectionRange(pos, pos)
      } catch {
        /* 忽略光标设置失败 */
      }
    })
    setShowPinCards(false)
    message.success(`已插入：${card.paper_title}${anchor}`)
  }

  // ---- 插入综述段落（Q1-2）：把生成的综述作为正式内容块插入草稿并保存 ----
  const insertReview = async (text: string, citations: ReviewCitation[]) => {
    const body = (text || '').trim()
    const ta = draftRef.current?.resizableTextArea?.textArea
    const start = ta?.selectionStart ?? draft.length
    const end = ta?.selectionEnd ?? start
    const block = `\n\n${body}\n`
    const next = draft.slice(0, start) + block + draft.slice(end)
    setDraft(next)
    const pos = start + block.length
    requestAnimationFrame(() => {
      ta?.focus()
      try {
        ta?.setSelectionRange(pos, pos)
      } catch {
        /* 忽略光标设置失败 */
      }
    })
    setShowReviewModal(false)
    if (project) await persist({ content: next })
    message.success(`已插入综述段落（引用 ${citations.length} 条），并保存到项目内容`)
  }

  // ---- 步骤5 ----
  const onGenerateAbstracts = async () => {
    if (!project) return
    setBusy(true)
    try {
      const res = await projectsApi.generateAbstracts(project.id)
      setAbstractZh(res.zh.abstract)
      setKeywordsZh(res.zh.keywords)
      setAbstractEn(res.en.abstract)
      setKeywordsEn(res.en.keywords)
      const outline = {
        ...(project.outline || {}),
        sections,
        abstract_zh: res.zh.abstract,
        abstract_en: res.en.abstract,
        keywords_zh: res.zh.keywords,
        keywords_en: res.en.keywords,
      }
      await persist({ outline })
      message.success('中英文摘要与关键词已生成')
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  // ---- 步骤6 ----
  const onExport = () => {
    if (!project) return
    fetch(projectsApi.exportWordUrl(project.id), {
      headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error('导出失败')
        return res.blob()
      })
      .then((blob) => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `${project.title || '论文'}.docx`
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch((err) => message.error(err.message))
  }

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    )
  }

  return (
    <div>
      <Typography.Title level={4}>论文写作向导</Typography.Title>
      <Steps
        current={current}
        onChange={(s) => goTo(s)}
        items={STEP_TITLES.map((t) => ({ title: t }))}
        style={{ marginBottom: 24 }}
      />

      {busy && (
        <div style={{ textAlign: 'center', padding: 24 }}>
          <Spin tip="AI 正在生成..." />
        </div>
      )}

      {/* 步骤1：选题 */}
      {current === 0 && (
        <Card title="第一步 — 选题">
          <Typography.Paragraph type="secondary">
            描述你的研究方向，让 AI 为你推荐具体的论文题目。
          </Typography.Paragraph>
          <Space style={{ marginBottom: 12 }}>
            <Typography.Text type="secondary">生成语言</Typography.Text>
            <Segmented
              options={[
                { label: '中文', value: 'zh' },
                { label: 'English', value: 'en' },
              ]}
              value={lang}
              onChange={(v) => setLang(v as 'zh' | 'en')}
            />
          </Space>
          <TextArea
            value={direction}
            onChange={(e) => setDirection(e.target.value)}
            placeholder="例如：利用大语言模型进行自动化科研文献综述"
            rows={3}
            style={{ marginBottom: 12 }}
          />
          <Button type="primary" icon={<BulbOutlined />} onClick={onGenerateTitles} loading={busy}>
            生成建议
          </Button>
          {titles.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <Typography.Text strong>推荐题目：</Typography.Text>
              <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
                {titles.map((t) => (
                  <Col xs={24} md={12} key={t}>
                    <Card hoverable onClick={() => chooseTitle(t)} size="small">
                      {t}
                    </Card>
                  </Col>
                ))}
              </Row>
            </div>
          )}
        </Card>
      )}

      {/* 步骤2：大纲 */}
      {current === 1 && (
        <Card
          title="第二步 — 构建大纲"
          extra={
            <Space>
              <Segmented
                options={[
                  { label: '中文', value: 'zh' },
                  { label: 'English', value: 'en' },
                ]}
                value={lang}
                onChange={(v) => setLang(v as 'zh' | 'en')}
              />
              <Button onClick={onGenerateOutline} loading={busy}>自动生成（IMRaD）</Button>
              <Button
                icon={<PlusOutlined />}
                onClick={() => setSections((prev) => [...prev, { title: '新章节', points: [] }])}
              >
                添加章节
              </Button>
              <Button type="primary" icon={<SaveOutlined />} onClick={saveOutline}>
                保存
              </Button>
            </Space>
          }
        >
          {sections.length === 0 ? (
            <Empty description="还没有大纲。点击「自动生成」或手动添加章节。" />
          ) : (
            sections.map((sec, idx) => (
              <Card key={idx} size="small" style={{ marginBottom: 12 }}>
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Input
                    value={sec.title}
                    onChange={(e) => updateSection(idx, 'title', e.target.value)}
                    placeholder="章节标题"
                  />
                  <TextArea
                    value={(sec.points || []).join('\n')}
                    onChange={(e) =>
                      setSections((prev) => {
                        const next = [...prev]
                        next[idx] = { ...next[idx], points: e.target.value.split('\n') }
                        return next
                      })
                    }
                    placeholder="每行一个要点"
                    rows={3}
                  />
                  <Button danger size="small" onClick={() => setSections((prev) => prev.filter((_, i) => i !== idx))}>
                    删除章节
                  </Button>
                </Space>
              </Card>
            ))
          )}
        </Card>
      )}

      {/* 步骤3：素材 */}
      {current === 2 && (
        <Card
          title="第三步 — 从文库中选取素材"
          extra={
            <Button type="primary" onClick={onSearchMaterials} loading={busy} disabled={sections.length === 0}>
              查找素材
            </Button>
          }
        >
          {Object.keys(materials).length === 0 ? (
            <Empty description="点击「查找素材」，将根据各章节标题在你的文库中进行语义检索。" />
          ) : (
            Object.entries(materials).map(([section, items]) => (
              <div key={section} style={{ marginBottom: 16 }}>
                <Typography.Title level={5}>{section}</Typography.Title>
                {items.length === 0 ? (
                  <Typography.Text type="secondary">未找到匹配内容。</Typography.Text>
                ) : (
                  items.map((m) => (
                    <Card key={m.chunk_id} size="small" style={{ marginBottom: 8 }}>
                      <Checkbox
                        checked={selectedChunks.has(m.chunk_id)}
                        onChange={() => toggleChunk(m.chunk_id)}
                      >
                        <Space>
                          <Tag color="purple">{dimensionLabel[m.dimension] || m.dimension}</Tag>
                          <Typography.Text type="secondary">{m.paper_title}</Typography.Text>
                        </Space>
                        <div style={{ marginTop: 4, color: '#555' }}>{m.content}</div>
                      </Checkbox>
                    </Card>
                  ))
                )}
              </div>
            ))
          )}
        </Card>
      )}

      {/* 步骤4：草稿 */}
      {current === 3 && (
        <Card
          title="第四步 — 撰写草稿"
          extra={
            <Space>
              <Segmented
                options={[
                  { label: '中文', value: 'zh' },
                  { label: 'English', value: 'en' },
                ]}
                value={lang}
                onChange={(v) => setLang(v as 'zh' | 'en')}
              />
              <Button icon={<FileTextOutlined />} onClick={() => setShowReviewModal(true)}>
                生成综述段落
              </Button>
              <Button icon={<PushpinOutlined />} onClick={openPinCards}>
                从卡片笔记插入
              </Button>
              <Button onClick={() => onGenerateDraft()} loading={busy}>生成全部章节</Button>
              <Button type="primary" icon={<SaveOutlined />} onClick={saveDraft}>
                保存
              </Button>
            </Space>
          }
        >
          <Row gutter={16}>
            <Col xs={24} lg={12}>
              <Typography.Text strong>Markdown 编辑器</Typography.Text>
              <TextArea
                ref={draftRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                style={{ minHeight: 500, fontFamily: 'monospace' }}
              />
            </Col>
            <Col xs={24} lg={12}>
              <Typography.Text strong>预览</Typography.Text>
              <div
                className="markdown-body"
                style={{
                  minHeight: 500,
                  background: '#fafafa',
                  padding: 16,
                  borderRadius: 8,
                  overflow: 'auto',
                }}
              >
                <ReactMarkdown>{draft || '*暂无内容*'}</ReactMarkdown>
              </div>
            </Col>
          </Row>
          <Divider />
          <Typography.Text strong>生成单节：</Typography.Text>
          <Space wrap style={{ marginTop: 8 }}>
            {sections.map((s) => (
              <Button key={s.title} size="small" onClick={() => onGenerateDraft(s.title)} loading={busy}>
                {s.title}
              </Button>
            ))}
          </Space>
        </Card>
      )}

      {/* 步骤5：摘要 */}
      {current === 4 && (
        <Card
          title="第五步 — 摘要与关键词"
          extra={<Button type="primary" onClick={onGenerateAbstracts} loading={busy}>生成中英文摘要</Button>}
        >
          {(abstractZh || abstractEn) ? (
            <>
              <Typography.Title level={5}>中文摘要</Typography.Title>
              <TextArea value={abstractZh} onChange={(e) => setAbstractZh(e.target.value)} rows={8} />
              <Typography.Title level={5} style={{ marginTop: 12 }}>中文关键词</Typography.Title>
              <Space wrap>
                {keywordsZh.map((k) => (
                  <Tag key={k} color="blue">
                    {k}
                  </Tag>
                ))}
              </Space>
              <Divider />
              <Typography.Title level={5}>English Abstract</Typography.Title>
              <TextArea value={abstractEn} onChange={(e) => setAbstractEn(e.target.value)} rows={8} />
              <Typography.Title level={5} style={{ marginTop: 12 }}>Keywords</Typography.Title>
              <Space wrap>
                {keywordsEn.map((k) => (
                  <Tag key={k} color="geekblue">
                    {k}
                  </Tag>
                ))}
              </Space>
            </>
          ) : (
            <Empty description="根据草稿自动生成中英文摘要与关键词（国内论文摘要需双语）。" />
          )}
        </Card>
      )}

      {/* 步骤6：导出 */}
      {current === 5 && (
        <Card title="第六步 — 导出为 Word">
          <Typography.Paragraph>
            在下方预览最终文档，然后导出为 Word（.docx）文件。
          </Typography.Paragraph>
          {(abstractZh || abstractEn) && (
            <div style={{ background: '#f6f8fa', padding: 16, borderRadius: 8, marginBottom: 16 }}>
              <Typography.Title level={5}>中文摘要</Typography.Title>
              <Typography.Paragraph>{abstractZh || '（未生成）'}</Typography.Paragraph>
              <Space wrap>
                {keywordsZh.map((k) => (
                  <Tag key={k}>{k}</Tag>
                ))}
              </Space>
              <Divider />
              <Typography.Title level={5}>English Abstract</Typography.Title>
              <Typography.Paragraph>{abstractEn || '（未生成）'}</Typography.Paragraph>
              <Space wrap>
                {keywordsEn.map((k) => (
                  <Tag key={k}>{k}</Tag>
                ))}
              </Space>
            </div>
          )}
          <div
            className="markdown-body"
            style={{ background: '#fff', border: '1px solid #eee', padding: 24, borderRadius: 8, marginBottom: 16 }}
          >
            <ReactMarkdown>{draft || '## （草稿为空）'}</ReactMarkdown>
          </div>
          <Button type="primary" size="large" icon={<DownloadOutlined />} onClick={onExport}>
            导出为 Word
          </Button>
        </Card>
      )}

      {/* 步骤导航：上一步 / 下一步 */}
      <Row justify="space-between" style={{ marginTop: 20 }}>
        <Button disabled={current === 0} onClick={() => goTo(current - 1)}>
          上一步
        </Button>
        {current < 5 && (
          <Button type="primary" onClick={() => goTo(current + 1)}>
            下一步
          </Button>
        )}
      </Row>

      {/* 从卡片笔记插入弹窗（Q1-1）：点击卡片 → 插入到草稿光标处（带引用锚文本） */}
      <Modal
        title="从卡片笔记插入"
        open={showPinCards}
        onCancel={() => setShowPinCards(false)}
        footer={null}
        width={640}
      >
        {pinCards.length === 0 ? (
          <Empty description="还没有卡片笔记。在阅读器中选中文字并点击「📌 钉成卡片」即可创建。" />
        ) : (
          <List
            dataSource={pinCards}
            style={{ maxHeight: 420, overflow: 'auto' }}
            renderItem={(card) => (
              <List.Item
                style={{ cursor: 'pointer' }}
                onClick={() => insertPinCard(card)}
                title="点击插入到草稿光标处"
              >
                <List.Item.Meta
                  title={
                    <Space size={6} wrap>
                      <Tag color="blue">p{card.page ?? '-'}</Tag>
                      <Typography.Text strong>{card.note || card.snippet}</Typography.Text>
                    </Space>
                  }
                  description={
                    <Space size={6} wrap>
                      <Typography.Text type="secondary">{card.paper_title}</Typography.Text>
                      <Typography.Text type="secondary">{card.anchor}</Typography.Text>
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Modal>
    </div>
  )
}
