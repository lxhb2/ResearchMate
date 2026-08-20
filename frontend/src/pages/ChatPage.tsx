import { useEffect, useState } from 'react'
import {
  Row,
  Col,
  List,
  Button,
  Switch,
  Typography,
  Empty,
  Spin,
  message,
  Space,
  Popconfirm,
  Tag,
} from 'antd'
import {
  PlusOutlined,
  DeleteOutlined,
  BookOutlined,
  GlobalOutlined,
  RobotOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import type { Conversation } from '../types'
import { chatApi, conversationsApi } from '../api/chat'
import { papersApi, type LitReviewOptions, type ReviewCitation } from '../api/papers'
import { getErrorMessage } from '../api/client'
import { formatMarkdownContent } from '../utils/format'
import AtMentionInput from '../components/AtMentionInput'
import type { AgentContext } from '../api/agent'

const C = {
  bg: '#f6f7f9',
  panel: '#ffffff',
  border: '#e5e7eb',
  text: '#1f2329',
  sub: '#8a9099',
  accent: '#6366f1',
  accentSoft: '#eef0ff',
  userBg: '#6366f1',
  assistantBg: '#f3f4f6',
}

export default function ChatPage() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [active, setActive] = useState<Conversation | null>(null)
  const [input, setInput] = useState('')
  const [contexts, setContexts] = useState<AgentContext[]>([])
  const [loading, setLoading] = useState(false)
  const [useLibrary, setUseLibrary] = useState(true)
  const [webSearch, setWebSearch] = useState(false)
  const [agentStatus, setAgentStatus] = useState('')
  // 多文档综述（Q1-2）：当前综述的引用来源（渲染 citation 芯片）
  const [reviewCitations, setReviewCitations] = useState<ReviewCitation[]>([])

  const loadConversations = async () => {
    try {
      const list = await conversationsApi.list()
      setConversations(list)
    } catch (err) {
      message.error(getErrorMessage(err))
    }
  }

  useEffect(() => {
    loadConversations()
    // 从文献库「生成综述…」跳转过来时，消费预设并自动开始流式生成
    const raw = sessionStorage.getItem('lit-review-preset')
    if (raw) {
      sessionStorage.removeItem('lit-review-preset')
      try {
        const preset = JSON.parse(raw) as LitReviewOptions & { title?: string }
        startLiteratureReview(preset)
      } catch {
        /* 预设解析失败则忽略 */
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 多文档综述：新建会话并流式生成（逐段 + 引用芯片）
  const startLiteratureReview = async (preset: LitReviewOptions & { title?: string }) => {
    const n = preset.paper_ids.length
    const structureLabel = { thematic: '主题式', chronological: '时间线式', gap_analysis: '研究空白分析' }[
      preset.structure
    ] || '主题式'
    const styleLabel = { apa: 'APA', gb7714: 'GB/T 7714', bibtex_citekey: 'BibTeX cite key' }[
      preset.citation_style
    ] || 'APA'
    const userMsg = `📚 生成综述：${preset.topic}\n\n（基于所选 ${n} 篇文献 · ${structureLabel} · ${styleLabel} 引用）`
    setActive(null)
    setReviewCitations([])
    const userM = { role: 'user' as const, content: userMsg }
    const assistantM = { role: 'assistant' as const, content: '' }
    setActive({
      id: '',
      title: `综述：${(preset.topic || '').slice(0, 30)}`,
      messages: [userM, assistantM],
      created_at: '',
      updated_at: '',
    })
    setLoading(true)
    try {
      await papersApi.literatureReview(
        preset,
        (delta) => {
          setActive((prev) => {
            if (!prev) return prev
            const msgs = [...(prev.messages || [])]
            const last = msgs[msgs.length - 1]
            msgs[msgs.length - 1] = { ...last, content: (last.content || '') + delta }
            return { ...prev, messages: msgs }
          })
        },
        (citations) => setReviewCitations(citations),
      )
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const selectConversation = async (id: string) => {
    try {
      const conv = await conversationsApi.get(id)
      setActive(conv)
    } catch (err) {
      message.error(getErrorMessage(err))
    }
  }

  const newChat = () => {
    setActive(null)
    setInput('')
    setContexts([])
    setAgentStatus('')
  }

  const removeConv = async (id: string) => {
    try {
      await conversationsApi.remove(id)
      if (active?.id === id) setActive(null)
      loadConversations()
    } catch (err) {
      message.error(getErrorMessage(err))
    }
  }

  const send = async () => {
    const msg = (input || '').trim()
    if (!msg) return
    const sentContexts = contexts
    setInput('')
    setContexts([])
    // 先插入用户消息 + 空的助手消息占位，之后流式填充助手消息
    const userMsg = { role: 'user' as const, content: msg }
    const assistantMsg = { role: 'assistant' as const, content: '' }
    const newMsgs = [...(active?.messages || []), userMsg, assistantMsg]
    const assistantIndex = newMsgs.length - 1
    setActive((prev) => ({
      ...(prev || ({} as Conversation)),
      id: prev?.id || '',
      user_id: '',
      title: prev?.title || msg.slice(0, 40),
      messages: newMsgs,
      created_at: prev?.created_at || '',
      updated_at: prev?.updated_at || '',
    }))
    setLoading(true)
    setAgentStatus('正在思考…')
    try {
      const convId = await chatApi.sendEvents(msg, active?.id, useLibrary, webSearch, sentContexts, (evt) => {
        if (evt.type === 'thinking') setAgentStatus('正在思考…')
        else if (evt.type === 'tool_start') setAgentStatus(`正在调用工具：${evt.tool}`)
        else if (evt.type === 'tool_result') setAgentStatus('工具调用完成，正在整理回答…')
        else if (evt.type === 'answer') {
          setAgentStatus('')
          setActive((prev) => {
            if (!prev) return prev
            const msgs = [...(prev.messages || [])]
            msgs[assistantIndex] = { ...assistantMsg, content: evt.answer || '' }
            return { ...prev, messages: msgs }
          })
        } else if (evt.type === 'error') {
          setAgentStatus('')
          setActive((prev) => {
            if (!prev) return prev
            const msgs = [...(prev.messages || [])]
            msgs[assistantIndex] = { ...assistantMsg, content: `⚠️ ${evt.error || '处理失败'}` }
            return { ...prev, messages: msgs }
          })
        }
      })
      if (convId) setActive((prev) => (prev ? { ...prev, id: convId } : prev))
      loadConversations()
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setLoading(false)
      setAgentStatus('')
    }
  }

  return (
    <Row gutter={12} style={{ height: '100%' }}>
      <Col xs={24} md={7} lg={6}>
        <div
          style={{
            background: C.panel,
            borderRadius: 12,
            border: `1px solid ${C.border}`,
            height: '100%',
            overflow: 'auto',
            padding: 10,
          }}
        >
          <Button
            block
            icon={<PlusOutlined />}
            onClick={newChat}
            style={{ marginBottom: 10, background: C.accentSoft, borderColor: C.border, color: C.text }}
          >
            新建对话
          </Button>
          <List
            dataSource={conversations}
            locale={{ emptyText: <Empty description="暂无对话" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
            renderItem={(conv) => (
              <List.Item
                style={{
                  cursor: 'pointer',
                  background: active?.id === conv.id ? C.accentSoft : 'transparent',
                  padding: '8px 12px',
                  borderRadius: 8,
                  border: `1px solid ${active?.id === conv.id ? C.border : 'transparent'}`,
                }}
                onClick={() => selectConversation(conv.id)}
                actions={[
                  <Popconfirm
                    key="del"
                    title="删除该对话？"
                    okText="删除"
                    cancelText="取消"
                    onConfirm={(e) => {
                      e?.stopPropagation()
                      removeConv(conv.id)
                    }}
                  >
                    <DeleteOutlined style={{ color: C.sub }} onClick={(e) => e.stopPropagation()} />
                  </Popconfirm>,
                ]}
              >
                <Typography.Text ellipsis style={{ maxWidth: 150, color: C.text }}>
                  {conv.title || '未命名'}
                </Typography.Text>
              </List.Item>
            )}
          />
        </div>
      </Col>

      <Col xs={24} md={17} lg={18}>
        <div
          style={{
            background: C.panel,
            borderRadius: 12,
            border: `1px solid ${C.border}`,
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}
        >
          {/* 头部 */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '10px 16px',
              borderBottom: `1px solid ${C.border}`,
              background: C.bg,
            }}
          >
            <Space>
              <RobotOutlined style={{ color: C.accent }} />
              <Typography.Text strong style={{ color: C.text }}>
                全局助手对话
              </Typography.Text>
              <Tag style={{ background: C.accentSoft, border: `1px solid #d8dcff`, color: C.accent }}>
                codex · @引用
              </Tag>
            </Space>
            <Space>
              <Space size={4}>
                <BookOutlined style={{ color: C.sub }} />
                <span style={{ color: C.sub, fontSize: 13 }}>文库</span>
                <Switch size="small" checked={useLibrary} onChange={setUseLibrary} />
              </Space>
              <Space size={4}>
                <GlobalOutlined style={{ color: C.sub }} />
                <span style={{ color: C.sub, fontSize: 13 }}>联网</span>
                <Switch size="small" checked={webSearch} onChange={setWebSearch} />
              </Space>
            </Space>
          </div>

          {/* 消息区 */}
          <div style={{ flex: 1, overflow: 'auto', padding: 16, background: C.bg }}>
            {!active?.messages?.length ? (
              <div style={{ textAlign: 'center', marginTop: 80 }}>
                <RobotOutlined style={{ fontSize: 48, color: C.border }} />
                <div style={{ color: C.sub, marginTop: 12 }}>
                  开始一段对话吧，提出你的科研问题。
                  <br />
                  <span style={{ fontSize: 12 }}>输入 @ 可引用技能 / 工具 / 记忆 / 模块</span>
                </div>
              </div>
            ) : (
              active.messages.map((m, i) => (
                <div
                  key={i}
                  style={{ margin: '14px 0', display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}
                >
                  <div
                    style={{
                      display: 'inline-block',
                      padding: '10px 14px',
                      borderRadius: 12,
                      background: m.role === 'user' ? C.userBg : C.assistantBg,
                      color: m.role === 'user' ? '#fff' : C.text,
                      border: m.role === 'assistant' ? `1px solid ${C.border}` : 'none',
                      maxWidth: '82%',
                      textAlign: 'left',
                      fontSize: 14,
                      lineHeight: 1.7,
                    }}
                  >
                    <ReactMarkdown>{formatMarkdownContent(m.content)}</ReactMarkdown>
                    {/* 多文档综述：引用来源芯片（Q1-2） */}
                    {m.role === 'assistant' && i === active.messages.length - 1 && reviewCitations.length > 0 && (
                      <div
                        style={{
                          marginTop: 8,
                          padding: '6px 8px',
                          background: '#eef0ff',
                          borderRadius: 6,
                          fontSize: 12,
                        }}
                      >
                        <div style={{ color: '#4f46e5', fontWeight: 600, marginBottom: 4 }}>
                          引用来源（{reviewCitations.length}）
                        </div>
                        {reviewCitations.map((c, ci) => (
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
                </div>
              ))
            )}
            {loading && (
              <div style={{ textAlign: 'center', padding: 12 }}>
                <Spin size="small" />
                <div style={{ color: C.sub, fontSize: 12, marginTop: 6 }}>{agentStatus || '助手思考中…'}</div>
              </div>
            )}
          </div>

          {/* 输入区 */}
          <div style={{ padding: 12, borderTop: `1px solid ${C.border}`, background: C.panel }}>
            <AtMentionInput
              value={input}
              onChange={setInput}
              contexts={contexts}
              onContextsChange={setContexts}
              placeholder="输入消息，@ 引用技能/工具/记忆/模块…（回车发送，Shift+回车换行）"
              disabled={loading}
              onSend={send}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
              <Button type="primary" icon={<PlusOutlined />} disabled={!input.trim()} loading={loading} onClick={send} style={{ background: C.accent, minWidth: 100 }}>
                发送
              </Button>
            </div>
          </div>
        </div>
      </Col>
    </Row>
  )
}
