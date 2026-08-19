import { useEffect, useRef, useState } from 'react'
import { Input, Empty } from 'antd'
import {
  ApiOutlined,
  ExperimentOutlined,
  BookOutlined,
  AppstoreOutlined,
  CloseOutlined,
} from '@ant-design/icons'
import { agentApi, type ContextItem, type AgentContext } from '../api/agent'

const { TextArea } = Input

const TYPE_META: Record<string, { icon: JSX.Element; color: string }> = {
  skill: { icon: <ExperimentOutlined />, color: '#a78bfa' },
  tool: { icon: <ApiOutlined />, color: '#22d3ee' },
  memory: { icon: <BookOutlined />, color: '#fbbf24' },
  module: { icon: <AppstoreOutlined />, color: '#34d399' },
}

interface AtMentionInputProps {
  value: string
  onChange: (v: string) => void
  contexts: AgentContext[]
  onContextsChange: (ctx: AgentContext[]) => void
  placeholder?: string
  dark?: boolean
  autoFocus?: boolean
  onSend?: () => void
  disabled?: boolean
}

/** Codex 风格 @ 引用输入：输入 @ 弹出可引用对象（技能/工具/记忆/模块），
 *  选中后以 chip 形式加入上下文并随消息一起发送。 */
export default function AtMentionInput({
  value,
  onChange,
  contexts,
  onContextsChange,
  placeholder,
  dark = false,
  autoFocus,
  onSend,
  disabled,
}: AtMentionInputProps) {
  const [catalog, setCatalog] = useState<ContextItem[]>([])
  const [menu, setMenu] = useState<{ query: string; items: ContextItem[]; start: number } | null>(null)
  const [sel, setSel] = useState(0)
  const taRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    agentApi
      .contexts()
      .then(setCatalog)
      .catch(() => setCatalog([]))
  }, [])

  const handleChange = (v: string, selStart: number) => {
    onChange(v)
    const upto = v.slice(0, selStart)
    const at = upto.lastIndexOf('@')
    if (at >= 0) {
      const tail = upto.slice(at + 1)
      if (!/\s/.test(tail) && tail.length <= 40) {
        const query = tail.toLowerCase()
        const items = catalog
          .filter((i) => !query || (i.name + i.label + i.description + (i.triggers || []).join(' ')).toLowerCase().includes(query))
          .slice(0, 8)
        setMenu({ query, items, start: at })
        setSel(0)
        return
      }
    }
    setMenu(null)
  }

  const pick = (item: ContextItem) => {
    if (!menu) return
    const before = value.slice(0, menu.start)
    const after = value.slice(menu.start).replace(/^@[^\s]*/, '')
    onChange(before + `@${item.name} ` + after)
    onContextsChange([...contexts, { type: item.type, name: item.name }])
    setMenu(null)
    requestAnimationFrame(() => taRef.current?.focus())
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!menu) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        onSend?.()
      }
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSel((s) => (s + 1) % Math.max(menu.items.length, 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSel((s) => (s - 1 + Math.max(menu.items.length, 1)) % Math.max(menu.items.length, 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (menu.items[sel]) pick(menu.items[sel])
    } else if (e.key === 'Escape') {
      e.preventDefault()
      setMenu(null)
    }
  }

  const removeCtx = (i: number) => {
    onContextsChange(contexts.filter((_, idx) => idx !== i))
  }

  const fg = dark ? '#e5e7eb' : '#111'
  const sub = dark ? '#6b7280' : '#8c8c8c'
  const border = dark ? '#2d333b' : '#d9d9d9'

  return (
    <div style={{ position: 'relative' }}>
      {/* 已选 @ 上下文 chips */}
      {contexts.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
          {contexts.map((c, i) => {
            const meta = TYPE_META[c.type] || TYPE_META.tool
            return (
              <span
                key={`${c.type}:${c.name}:${i}`}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  padding: '2px 10px',
                  borderRadius: 999,
                  fontSize: 12,
                  border: `1px solid ${meta.color}55`,
                  background: dark ? `${meta.color}22` : `${meta.color}18`,
                  color: meta.color,
                }}
              >
                {meta.icon}
                <span>{c.name}</span>
                <CloseOutlined
                  style={{ fontSize: 10, cursor: 'pointer', opacity: 0.7 }}
                  onClick={() => removeCtx(i)}
                />
              </span>
            )
          })}
        </div>
      )}

      <TextArea
        ref={taRef as never}
        value={value}
        onChange={(e) => handleChange(e.target.value, e.target.selectionStart ?? e.target.value.length)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder || '输入消息，@ 可引用技能/工具/记忆/模块…（回车发送）'}
        autoSize={{ minRows: 1, maxRows: 4 }}
        disabled={disabled}
        autoFocus={autoFocus}
        style={{
          background: dark ? '#0d1117' : '#fff',
          color: fg,
          borderColor: border,
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
          fontSize: 13,
        }}
        onPressEnter={(e) => {
          if (!e.shiftKey && !menu) {
            e.preventDefault()
            onSend?.()
          }
        }}
      />

      {/* @ 下拉菜单 */}
      {menu && menu.items.length > 0 && (
        <div
          style={{
            position: 'absolute',
            bottom: '100%',
            left: 0,
            right: 0,
            marginBottom: 6,
            maxHeight: 260,
            overflow: 'auto',
            borderRadius: 10,
            border: `1px solid ${dark ? '#30363d' : '#e5e7eb'}`,
            background: dark ? '#161b22' : '#fff',
            boxShadow: '0 8px 24px rgba(0,0,0,.18)',
            zIndex: 30,
            padding: 4,
          }}
        >
          {menu.items.map((item, i) => {
            const meta = TYPE_META[item.type] || TYPE_META.tool
            return (
              <div
                key={`${item.type}:${item.name}`}
                onMouseDown={(e) => {
                  e.preventDefault()
                  pick(item)
                }}
                onMouseEnter={() => setSel(i)}
                style={{
                  display: 'flex',
                  gap: 8,
                  padding: '6px 10px',
                  borderRadius: 6,
                  cursor: 'pointer',
                  background: i === sel ? (dark ? '#21262d' : '#f0f0ff') : 'transparent',
                }}
              >
                <span style={{ color: meta.color, marginTop: 2 }}>{meta.icon}</span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: fg, whiteSpace: 'nowrap' }}>
                    {item.name}
                    <span style={{ fontWeight: 400, color: sub, marginLeft: 8, fontSize: 12 }}>{item.label}</span>
                  </div>
                  <div
                    style={{ fontSize: 12, color: sub, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  >
                    {item.description || (item.triggers || []).join(' / ')}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
      {menu && menu.items.length === 0 && (
        <div
          style={{
            position: 'absolute',
            bottom: '100%',
            left: 0,
            right: 0,
            marginBottom: 6,
            borderRadius: 10,
            border: `1px solid ${dark ? '#30363d' : '#e5e7eb'}`,
            background: dark ? '#161b22' : '#fff',
            boxShadow: '0 8px 24px rgba(0,0,0,.18)',
            zIndex: 30,
            padding: '10px 0',
          }}
        >
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的引用对象" style={{ margin: 0 }} />
        </div>
      )}
    </div>
  )
}
