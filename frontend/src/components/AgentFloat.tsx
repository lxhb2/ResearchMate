import { useEffect, useRef, useState } from 'react'
import { Button, Tag, Typography, Space, Divider } from 'antd'
import {
  RobotOutlined,
  CloseOutlined,
  SendOutlined,
  ThunderboltOutlined,
  BookOutlined,
  EditOutlined,
  ApartmentOutlined,
  MessageOutlined,
  SettingOutlined,
  GithubOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import { useNavigate, useLocation } from 'react-router-dom'
import { agentApi, type Recommendation, type ModuleInfo, type AgentContext } from '../api/agent'
import { formatMarkdownContent } from '../utils/format'
import AtMentionInput from './AtMentionInput'

interface Msg {
  role: 'user' | 'assistant'
  content: string
}

const MODULE_ICONS: Record<string, React.ReactNode> = {
  book: <BookOutlined />,
  edit: <EditOutlined />,
  flow: <ApartmentOutlined />,
  chat: <MessageOutlined />,
  setting: <SettingOutlined />,
}

const WELCOME: Msg = {
  role: 'assistant',
  content:
    '你好，我是全局助手 👋\n\n我可以：\n- **智能推荐**：告诉我你想做什么，我会跳转到对应模块并引导操作\n- **工具调用**：联网搜索、API 一键配置、读写文件与长期记忆\n- **@ 引用**：输入 `@` 可引用技能 / 工具 / 记忆 / 模块\n- **长期记忆**：跨对话记住你的偏好\n\n试试说：*“我想导入一篇 PDF 论文”* 或 *“帮我配置一下大模型 API”*',
}

const C = {
  bg: '#f6f7f9',
  panel: '#ffffff',
  border: '#e5e7eb',
  text: '#1f2329',
  sub: '#8a9099',
  accent: '#6366f1',
  chip: '#6366f1',
  soft: '#eef0ff',
  assistantBg: '#f3f4f6',
  toolBg: '#ecfdf5',
  toolColor: '#059669',
}

export default function AgentFloat() {
  const [open, setOpen] = useState(false)
  const [showGuide, setShowGuide] = useState(false)
  const [messages, setMessages] = useState<Msg[]>([WELCOME])
  const [input, setInput] = useState('')
  const [contexts, setContexts] = useState<AgentContext[]>([])
  const [loading, setLoading] = useState(false)
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null)
  const [toolTrace, setToolTrace] = useState<{ tool: string }[]>([])
  const [modules, setModules] = useState<ModuleInfo[]>([])
  const [visited, setVisited] = useState(false)

  const navigate = useNavigate()
  const location = useLocation()
  const bodyRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    agentApi
      .modules()
      .then(setModules)
      .catch(() => {})
  }, [])

  // 自动滚动到底部
  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, recommendation, loading, toolTrace])

  // 首次展开：进入引导模式
  const openPanel = () => {
    setOpen(true)
    setShowGuide(!visited)
    setVisited(true)
  }

  const jumpTo = (path: string) => {
    navigate(path)
    setOpen(false)
    setShowGuide(false)
  }

  const send = async () => {
    const msg = (input || '').trim()
    if (!msg || loading) return
    const sentContexts = contexts
    setInput('')
    setContexts([])
    setRecommendation(null)
    setToolTrace([])
    setMessages((prev) => [...prev, { role: 'user', content: msg }, { role: 'assistant', content: '' }])
    setLoading(true)
    abortRef.current = new AbortController()
    try {
      await agentApi.chatStream(
        msg,
        false,
        false,
        (rec) => setRecommendation(rec),
        (trace) => setToolTrace(trace),
        (delta) => {
          setMessages((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (last && last.role === 'assistant') {
              next[next.length - 1] = { ...last, content: last.content + delta }
            }
            return next
          })
        },
        abortRef.current.signal,
        sentContexts,
      )
    } catch (err) {
      setMessages((prev) => {
        const next = [...prev]
        const last = next[next.length - 1]
        if (last && last.role === 'assistant' && !last.content) {
          next[next.length - 1] = { ...last, content: '（请求失败，请稍后重试，或到「设置」检查 API 配置）' }
        }
        return next
      })
    } finally {
      setLoading(false)
    }
  }

  const rec = recommendation

  const goSettings = () => {
    jumpTo('/settings')
  }

  return (
    <>
      {/* 悬浮按钮 */}
      {!open && (
        <button
          onClick={openPanel}
          style={{
            position: 'fixed',
            right: 24,
            bottom: 24,
            width: 56,
            height: 56,
            borderRadius: '50%',
            border: 'none',
            background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
            color: '#fff',
            fontSize: 24,
            cursor: 'pointer',
            boxShadow: '0 8px 24px rgba(99,102,241,.45)',
            zIndex: 1000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'transform .2s',
          }}
          title="全局助手"
        >
          <RobotOutlined />
        </button>
      )}

      {/* 悬浮窗面板（Codex 暗色风格） */}
      {open && (
        <div
          style={{
            position: 'fixed',
            right: 24,
            bottom: 24,
            width: 420,
            maxWidth: 'calc(100vw - 32px)',
            height: 580,
            maxHeight: 'calc(100vh - 48px)',
            background: C.panel,
            borderRadius: 14,
            border: `1px solid ${C.border}`,
            boxShadow: '0 12px 40px rgba(15,23,42,.16)',
            zIndex: 1000,
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
              padding: '10px 14px',
              background: C.bg,
              borderBottom: `1px solid ${C.border}`,
            }}
          >
            <Space>
              <RobotOutlined style={{ color: C.accent }} />
              <Typography.Text strong style={{ color: C.text }}>
                全局助手
              </Typography.Text>
              <Tag style={{ marginLeft: 4, background: C.soft, border: `1px solid #d8dcff`, color: C.chip }}>
                codex · @引用
              </Tag>
            </Space>
            <Space size={4}>
              <Button size="small" type="text" style={{ color: C.sub }} icon={<GithubOutlined />} title="GitHub 技能" onClick={goSettings} />
              {showGuide && (
                <Button size="small" type="text" style={{ color: C.chip }} icon={<ThunderboltOutlined />} onClick={() => setShowGuide(false)}>
                  去聊天
                </Button>
              )}
              <Button size="small" type="text" style={{ color: C.sub }} icon={<CloseOutlined />} onClick={() => setOpen(false)} />
            </Space>
          </div>

          {/* 智能推荐卡片（向导） */}
          {rec?.matched && rec.module && (
            <div style={{ padding: '10px 12px', borderBottom: `1px solid ${C.border}`, background: C.soft }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <Tag color="purple" style={{ margin: 0 }}>
                  智能推荐
                </Tag>
                <Typography.Text strong style={{ color: C.text }}>
                  {rec.reason}
                </Typography.Text>
              </div>
              <Typography.Text style={{ fontSize: 12, display: 'block', marginBottom: 8, color: C.sub }}>
                操作步骤：
              </Typography.Text>
              <ol style={{ margin: 0, paddingLeft: 18, marginBottom: 8 }}>
                {(rec.steps || []).map((s, i) => (
                  <li key={i} style={{ fontSize: 12, color: C.sub, marginBottom: 2 }}>
                    {s}
                  </li>
                ))}
              </ol>
              <Button
                type="primary"
                size="small"
                icon={MODULE_ICONS[rec.module.icon] || <ThunderboltOutlined />}
                onClick={() => jumpTo(rec.module!.path)}
              >
                跳转到「{rec.module.name}」并协助操作
              </Button>
            </div>
          )}

          {/* 引导模式：模块快捷入口 */}
          {showGuide && (
            <div style={{ padding: 12, borderBottom: `1px solid ${C.border}` }}>
              <Typography.Text strong style={{ display: 'block', marginBottom: 8, color: C.text }}>
                ✨ 想做什么？点击模块即可跳转，助手会协助你完成
              </Typography.Text>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                {modules.map((m) => (
                  <Button
                    key={m.key}
                    icon={MODULE_ICONS[m.icon] || <ThunderboltOutlined />}
                    onClick={() => jumpTo(m.path)}
                    style={{
                      textAlign: 'left',
                      height: 'auto',
                      padding: '8px 10px',
                      whiteSpace: 'normal',
                      background: '#f3f4f6',
                      borderColor: C.border,
                      color: C.text,
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 600 }}>{m.name}</div>
                      <div style={{ fontSize: 11, color: C.sub }}>{m.desc}</div>
                    </div>
                  </Button>
                ))}
              </div>
            </div>
          )}

          {/* 消息区 */}
          <div ref={bodyRef} style={{ flex: 1, overflow: 'auto', padding: 12, background: C.bg }}>
            {messages.map((m, i) => (
              <div
                key={i}
                style={{ margin: '10px 0', display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}
              >
                <div
                  style={{
                    maxWidth: '88%',
                    padding: '8px 12px',
                    borderRadius: 12,
                    background: m.role === 'user' ? C.accent : C.assistantBg,
                    color: m.role === 'user' ? '#fff' : C.text,
                    border: m.role === 'assistant' ? `1px solid ${C.border}` : 'none',
                    wordBreak: 'break-word',
                    fontFamily: m.role === 'assistant' ? 'inherit' : 'inherit',
                  }}
                >
                  {m.content ? (
                    <div style={{ fontSize: 13 }}>
                      <ReactMarkdown>{formatMarkdownContent(m.content)}</ReactMarkdown>
                    </div>
                  ) : (
                    <span style={{ opacity: 0.5, color: C.sub }}>思考中…</span>
                  )}
                </div>
              </div>
            ))}

            {toolTrace.length > 0 && (
              <div style={{ marginTop: 6 }}>
                <Divider style={{ margin: '4px 0', fontSize: 12, borderColor: C.border, color: C.sub }} plain>
                  已调用工具
                </Divider>
                <Space size={4} wrap>
                  {toolTrace.map((t, i) => (
                    <Tag key={i} style={{ background: C.toolBg, borderColor: '#bbf7d0', color: C.toolColor }}>
                      ⚡ {t.tool}
                    </Tag>
                  ))}
                </Space>
              </div>
            )}

            {loading && (
              <div style={{ textAlign: 'center', color: C.sub, fontSize: 12, marginTop: 4 }}>
                全局助手正在处理…（可联网 / 调用工具 / @ 引用）
              </div>
            )}
          </div>

          {/* 输入区 */}
          <div style={{ padding: 10, borderTop: `1px solid ${C.border}`, background: C.panel }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
              <div style={{ flex: 1 }}>
                <AtMentionInput
                  value={input}
                  onChange={setInput}
                  contexts={contexts}
                  onContextsChange={setContexts}
                  placeholder="输入消息，@ 引用技能/工具/记忆/模块…"
                  autoFocus
                  disabled={loading}
                  onSend={send}
                />
              </div>
              <Button
                type="primary"
                icon={<SendOutlined />}
                onClick={send}
                loading={loading}
                disabled={!input.trim()}
                style={{ background: C.accent, marginBottom: 2 }}
              />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
              <Typography.Text style={{ fontSize: 11, color: C.sub }}>
                当前页面：{location.pathname}
              </Typography.Text>
              <Typography.Text style={{ fontSize: 11, color: C.sub }}>@ 引用可把内容带入上下文</Typography.Text>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
