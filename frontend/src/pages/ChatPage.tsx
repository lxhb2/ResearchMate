import { useEffect, useState } from 'react'
import {
  Row,
  Col,
  List,
  Button,
  Input,
  Switch,
  Typography,
  Empty,
  Spin,
  message,
  Space,
  Popconfirm,
} from 'antd'
import { PlusOutlined, DeleteOutlined, SendOutlined, BookOutlined, GlobalOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import type { Conversation } from '../types'
import { chatApi, conversationsApi } from '../api/chat'
import { getErrorMessage } from '../api/client'

const { TextArea } = Input

export default function ChatPage() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [active, setActive] = useState<Conversation | null>(null)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [useLibrary, setUseLibrary] = useState(true)
  const [webSearch, setWebSearch] = useState(false)

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
  }, [])

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
    if (!input.trim()) return
    const msg = input.trim()
    setInput('')
    const msgs = [...(active?.messages || []), { role: 'user', content: msg }]
    setActive((prev) => ({
      ...(prev || ({} as Conversation)),
      id: prev?.id || '',
      user_id: '',
      title: prev?.title || msg.slice(0, 40),
      messages: msgs,
      created_at: prev?.created_at || '',
      updated_at: prev?.updated_at || '',
    }))
    setLoading(true)
    try {
      const res = await chatApi.send(msg, active?.id, useLibrary, webSearch)
      setActive(res.conversation)
      loadConversations()
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Row gutter={16} style={{ height: 'calc(100vh - 112px)' }}>
      <Col xs={24} md={7} lg={6}>
        <div style={{ background: '#fff', borderRadius: 8, height: '100%', overflow: 'auto', padding: 8 }}>
          <Button block icon={<PlusOutlined />} onClick={newChat} style={{ marginBottom: 8 }}>
            新建对话
          </Button>
          <List
            dataSource={conversations}
            locale={{ emptyText: <Empty description="暂无对话" /> }}
            renderItem={(conv) => (
              <List.Item
                style={{
                  cursor: 'pointer',
                  background: active?.id === conv.id ? '#f0f0ff' : 'transparent',
                  padding: '8px 12px',
                  borderRadius: 6,
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
                    <DeleteOutlined onClick={(e) => e.stopPropagation()} />
                  </Popconfirm>,
                ]}
              >
                <Typography.Text ellipsis style={{ maxWidth: 140 }}>
                  {conv.title || '未命名'}
                </Typography.Text>
              </List.Item>
            )}
          />
        </div>
      </Col>

      <Col xs={24} md={17} lg={18}>
        <div style={{ background: '#fff', borderRadius: 8, height: '100%', display: 'flex', flexDirection: 'column', padding: 16 }}>
          <Row justify="end" style={{ marginBottom: 8 }}>
            <Space>
              <Space size={4}>
                <BookOutlined />
                <span>文库</span>
                <Switch size="small" checked={useLibrary} onChange={setUseLibrary} />
              </Space>
              <Space size={4}>
                <GlobalOutlined />
                <span>联网</span>
                <Switch size="small" checked={webSearch} onChange={setWebSearch} />
              </Space>
            </Space>
          </Row>

          <div style={{ flex: 1, overflow: 'auto', paddingRight: 8 }}>
            {!active?.messages?.length ? (
              <Empty description="开始一段对话吧，提出你的科研问题。" />
            ) : (
              active.messages.map((m, i) => (
                <div key={i} style={{ margin: '12px 0', textAlign: m.role === 'user' ? 'right' : 'left' }}>
                  <div
                    style={{
                      display: 'inline-block',
                      padding: '10px 14px',
                      borderRadius: 12,
                      background: m.role === 'user' ? '#4f46e5' : '#f0f0f0',
                      color: m.role === 'user' ? '#fff' : '#000',
                      maxWidth: '80%',
                      textAlign: 'left',
                    }}
                  >
                    <ReactMarkdown>{m.content}</ReactMarkdown>
                  </div>
                </div>
              ))
            )}
            {loading && <Spin />}
          </div>

          <Space.Compact style={{ marginTop: 8 }}>
            <TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="输入消息...（回车发送，Shift+回车换行）"
              autoSize={{ minRows: 1, maxRows: 4 }}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
            />
            <Button type="primary" icon={<SendOutlined />} onClick={send} loading={loading} />
          </Space.Compact>
        </div>
      </Col>
    </Row>
  )
}
