import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Button,
  Input,
  Space,
  Typography,
  Tag,
  Spin,
  message,
  List,
  Divider,
  Empty,
} from 'antd'
import {
  ArrowLeftOutlined,
  SendOutlined,
  RobotOutlined,
  UserOutlined,
  CheckCircleOutlined,
  PlayCircleOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import { workflowApi, type WorkflowTemplate, type WorkflowRunResult } from '../api/workflow'
import { getErrorMessage } from '../api/client'

const { Text, Paragraph } = Typography

const VAR_HINTS: Record<string, string> = {
  topic: '研究主题',
  question: '研究问题 / 分析需求',
  data: '实验数据',
}

interface ChatMsg {
  id: string
  role: 'system' | 'user' | 'assistant'
  text: string
  kind?: 'confirm' | 'output' | 'log' | 'param'
  nodeStatus?: string
}

let msgSeq = 0
const nextId = () => `m${++msgSeq}`

/** 从工作流节点参数中提取所有 $user.xxx 变量键 */
function extractUserVars(nodes: Record<string, any>): string[] {
  const keys = new Set<string>()
  const re = /\$user\.([\w.]+)/g
  const walk = (val: any) => {
    if (typeof val === 'string') {
      let m: RegExpExecArray | null
      while ((m = re.exec(val)) !== null) keys.add(m![1])
    } else if (Array.isArray(val)) {
      val.forEach(walk)
    } else if (val && typeof val === 'object') {
      Object.values(val).forEach(walk)
    }
  }
  walk(nodes)
  return Array.from(keys)
}

/** 依据 start + next 指针，把节点排成可视化顺序列表 */
function orderedNodes(template: WorkflowTemplate): string[] {
  const edges: Record<string, string> = {}
  const nodes = template.nodes || {}
  for (const id of Object.keys(nodes)) {
    const n = nodes[id]
    if (n?.next) edges[id] = n.next
    else if (n?.type === 'condition' && n?.next_if_true) edges[id] = n.next_if_true
  }
  const order: string[] = []
  let cur = template.start
  const seen = new Set<string>()
  while (cur && nodes[cur] && !seen.has(cur)) {
    seen.add(cur)
    order.push(cur)
    cur = edges[cur]
  }
  return order
}

const NODE_LABEL: Record<string, string> = {
  tool: '工具',
  condition: '条件判断',
  confirm: '人工确认',
  end: '结束',
}

export default function DialogueRunView({
  template,
  onBack,
}: {
  template: WorkflowTemplate
  onBack: () => void
}) {
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const [pendingParams, setPendingParams] = useState<string[]>([])
  const [varMap, setVarMap] = useState<Record<string, any>>({})
  const [running, setRunning] = useState(false)
  const [runId, setRunId] = useState<string | null>(null)
  const [awaitingConfirm, setAwaitingConfirm] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  const userVars = useMemo(() => extractUserVars(template.nodes), [template.nodes])
  const ordered = useMemo(() => orderedNodes(template), [template])

  const push = (msg: Omit<ChatMsg, 'id'>) =>
    setMessages((ms) => [...ms, { ...msg, id: nextId() }])

  // 初次进入：打招呼 + 引导收集参数
  useEffect(() => {
    const varList = extractUserVars(template.nodes)
    setPendingParams(varList)
    push({
      role: 'system',
      text: `已加载模板「${template.name}」。\n${template.description || ''}\n\n工作流共 ${ordered.length} 个步骤。`,
    })
    if (varList.length === 0) {
      push({ role: 'system', text: '该模板无需额外参数，直接输入任意内容即可开始执行。' })
    } else {
      push({
        role: 'system',
        text: `开始前需要你提供 ${varList.length} 项信息，我会依次询问。`,
        kind: 'param',
      })
      askNextParam(varList, 0)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const askNextParam = (params: string[], idx: number) => {
    if (idx >= params.length) return
    const key = params[idx]
    push({ role: 'system', text: `请提供【${VAR_HINTS[key] || key}】：`, kind: 'param' })
  }

  const runWorkflow = async (vars: Record<string, any>, startMsgId?: string) => {
    setRunning(true)
    push({ role: 'system', text: '开始执行工作流…', kind: 'log' })
    try {
      const wfJson = { start: template.start, nodes: template.nodes, output: template.output }
      const result = await workflowApi.run(wfJson, vars)
      handleRunResult(result)
    } catch (err) {
      push({ role: 'system', text: '执行出错：' + getErrorMessage(err), kind: 'log' })
      setRunning(false)
    }
  }

  const handleRunResult = async (result: WorkflowRunResult) => {
    setRunId(result.run_id)
    // 节点日志
    ;(result.logs || []).forEach((log: any) => {
      const label = NODE_LABEL[log.node_type] || '节点'
      const icon = log.status === 'success' ? '✓' : log.status === 'failed' ? '✗' : '…'
      push({
        role: 'system',
        text: `${icon}【${label} ${log.node_id}】${log.detail || ''}`,
        kind: 'log',
        nodeStatus: log.status,
      })
    })
    if (result.status === 'awaiting_confirm') {
      setAwaitingConfirm(true)
      const pendingId = result.pending_confirm_nodes?.[0]
      const node = pendingId ? template.nodes[pendingId] : undefined
      push({
        role: 'system',
        text: `🔔 需要你的确认：${node?.stage || '本阶段'}。\n\n${node?.guide || '请阅读后点击「已了解，继续」进入下一步。'}`,
        kind: 'confirm',
      })
    } else if (result.status === 'success') {
      setAwaitingConfirm(false)
      push({
        role: 'assistant',
        text:
          result.final_output != null
            ? (typeof result.final_output === 'string'
              ? result.final_output
              : '```json\n' + JSON.stringify(result.final_output, null, 2) + '\n```')
            : '✅ 工作流执行完成。',
        kind: 'output',
      })
    } else if (result.status === 'failed') {
      setAwaitingConfirm(false)
      push({ role: 'system', text: '❌ 执行失败：' + (result.error || '未知错误'), kind: 'log' })
    } else {
      setAwaitingConfirm(false)
      push({ role: 'system', text: `状态：${result.status}`, kind: 'log' })
    }
    setRunning(false)
  }

  const handleSend = async () => {
    const text = input.trim()
    if (!text || running) return
    setInput('')
    push({ role: 'user', text })

    if (pendingParams.length > 0) {
      const key = pendingParams[0]
      const next = { ...varMap, [key]: text }
      setVarMap(next)
      const rest = pendingParams.slice(1)
      setPendingParams(rest)
      if (rest.length === 0) {
        push({ role: 'system', text: '信息已齐全，开始执行…', kind: 'log' })
        await runWorkflow(next)
      } else {
        askNextParam(rest, 0)
      }
      return
    }

    // 无参数或参数已齐全：直接执行
    await runWorkflow(varMap)
  }

  const handleResume = async () => {
    if (!runId || running) return
    setRunning(true)
    try {
      const result = await workflowApi.resume(runId)
      handleRunResult(result)
    } catch (err) {
      push({ role: 'system', text: '继续执行出错：' + getErrorMessage(err), kind: 'log' })
      setRunning(false)
    }
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div style={{ display: 'flex', gap: 16, height: 'calc(100vh - 120px)' }}>
      {/* 左侧：工作流预览 */}
      <div style={{ width: 260, border: '1px solid #f0f0f0', borderRadius: 8, padding: 12, overflow: 'auto', background: '#fafafa' }}>
        <Space style={{ marginBottom: 8 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={onBack}>返回</Button>
        </Space>
        <Tag color={template.source === 'custom' ? 'purple' : 'blue'}>
          {template.source === 'custom' ? '我的模板' : '默认模板'}
        </Tag>
        <div style={{ marginTop: 8 }}>
          <Text strong>{template.name}</Text>
        </div>
        <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 4 }}>{template.description}</Paragraph>
        <Divider style={{ margin: '10px 0' }} />
        <Text strong style={{ fontSize: 12 }}>工作流步骤</Text>
        {ordered.length === 0 ? (
          <Empty description="无节点" imageStyle={{ height: 40 }} />
        ) : (
          <List
            size="small"
            dataSource={ordered}
            renderItem={(id, idx) => {
              const node = template.nodes[id]
              const label =
                node?.type === 'tool'
                  ? node?.tool || '工具'
                  : NODE_LABEL[node?.type] || node?.type || id
              return (
                <List.Item style={{ padding: '4px 0' }}>
                  <Space size={6}>
                    <Tag color="default" style={{ marginRight: 0 }}>{idx + 1}</Tag>
                    <FileTextOutlined style={{ fontSize: 12 }} />
                    <Text style={{ fontSize: 12 }}>{label}</Text>
                  </Space>
                </List.Item>
              )
            }}
          />
        )}
      </div>

      {/* 右侧：对话区 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', border: '1px solid #f0f0f0', borderRadius: 8, overflow: 'hidden' }}>
        <div style={{ padding: '10px 16px', borderBottom: '1px solid #f0f0f0', background: '#fafafa' }}>
          <Space>
            <RobotOutlined style={{ color: '#1677ff' }} />
            <Text strong>对话式执行：{template.name}</Text>
          </Space>
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: 16, background: '#fff' }}>
          {messages.length === 0 && <Spin />}
          {messages.map((m) =>
            m.role === 'user' ? (
              <div key={m.id} style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
                <div
                  style={{
                    maxWidth: '70%',
                    background: '#1677ff',
                    color: '#fff',
                    borderRadius: 12,
                    borderTopRightRadius: 2,
                    padding: '8px 12px',
                    whiteSpace: 'pre-wrap',
                    fontSize: 13,
                  }}
                >
                  {m.text}
                </div>
                <UserOutlined style={{ marginLeft: 8, marginTop: 6, color: '#999' }} />
              </div>
            ) : m.kind === 'confirm' ? (
              <div key={m.id} style={{ display: 'flex', marginBottom: 12 }}>
                <RobotOutlined style={{ marginRight: 8, marginTop: 6, color: '#1677ff' }} />
                <div style={{ maxWidth: '78%', borderRadius: 12, borderTopLeftRadius: 2, padding: '10px 12px', background: '#fff7e6', border: '1px solid #ffd591' }}>
                  <Typography.Text style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{m.text}</Typography.Text>
                  <div style={{ marginTop: 10 }}>
                    <Button type="primary" size="small" icon={<CheckCircleOutlined />} loading={running} onClick={handleResume}>
                      已了解，继续
                    </Button>
                  </div>
                </div>
              </div>
            ) : (
              <div key={m.id} style={{ display: 'flex', marginBottom: 12 }}>
                <RobotOutlined style={{ marginRight: 8, marginTop: 6, color: '#1677ff' }} />
                <div
                  style={{
                    maxWidth: '78%',
                    borderRadius: 12,
                    borderTopLeftRadius: 2,
                    padding: '8px 12px',
                    background: m.kind === 'output' ? '#f6ffed' : '#f6f8fa',
                    border: m.kind === 'output' ? '1px solid #b7eb8f' : '1px solid #f0f0f0',
                    fontSize: 13,
                    whiteSpace: 'pre-wrap',
                  }}
                >
                  {m.kind === 'output' ? (
                    <ReactMarkdown>{m.text}</ReactMarkdown>
                  ) : (
                    <span style={{ whiteSpace: 'pre-wrap' }}>{m.text}</span>
                  )}
                </div>
              </div>
            ),
          )}
          <div ref={bottomRef} />
        </div>

        <div style={{ padding: 12, borderTop: '1px solid #f0f0f0', display: 'flex', gap: 8, background: '#fafafa' }}>
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={handleSend}
            placeholder={pendingParams.length > 0 ? '在此输入回答…' : awaitingConfirm ? '等待确认中…' : '输入研究主题/参数后回车，自动执行…'}
            disabled={running || awaitingConfirm}
            prefix={<PlayCircleOutlined style={{ color: '#bfbfbf' }} />}
          />
          <Button type="primary" icon={<SendOutlined />} loading={running} onClick={handleSend} disabled={awaitingConfirm}>
            发送
          </Button>
        </div>
      </div>
    </div>
  )
}