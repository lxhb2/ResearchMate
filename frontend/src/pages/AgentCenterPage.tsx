import { useEffect, useState } from 'react'
import {
  Card,
  Tabs,
  Table,
  Button,
  Input,
  Space,
  Tag,
  Typography,
  Popconfirm,
  Form,
  Select,
  Modal,
  List,
  message,
  Empty,
  Tooltip,
  Upload,
  Divider,
  Spin,
} from 'antd'
import {
  ThunderboltOutlined,
  PlusOutlined,
  DeleteOutlined,
  ApiOutlined,
  ExperimentOutlined,
  EyeOutlined,
  UploadOutlined,
  GithubOutlined,
  SearchOutlined,
  DownloadOutlined,
  CheckCircleOutlined,
  StarOutlined,
} from '@ant-design/icons'
import type { UploadProps } from 'antd'
import { agentApi, type SkillInfo, type McpServer, type MemoryFile, type GithubRepo } from '../api/agent'
import { getErrorMessage } from '../api/client'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

export default function AgentCenterPage({ embedded = false }: { embedded?: boolean }) {
  const [tab, setTab] = useState('skills')

  // ---- Skill 状态 ----
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [skillModal, setSkillModal] = useState(false)
  const [skillForm] = Form.useForm()

  // ---- GitHub 导入状态 ----
  const [githubQuery, setGithubQuery] = useState('')
  const [githubResults, setGithubResults] = useState<GithubRepo[]>([])
  const [githubLoading, setGithubLoading] = useState(false)
  const [importingRepo, setImportingRepo] = useState<string | null>(null)

  // ---- MCP 状态 ----
  const [servers, setServers] = useState<McpServer[]>([])
  const [mcpModal, setMcpModal] = useState(false)
  const [mcpForm] = Form.useForm()

  // ---- 记忆状态 ----
  const [memFiles, setMemFiles] = useState<MemoryFile[]>([])
  const [memView, setMemView] = useState<{ name: string; title: string; content: string } | null>(null)
  const [memDraft, setMemDraft] = useState('')

  const loadSkills = async () => {
    try {
      const data = await agentApi.skillsList()
      setSkills(data.skills || [])
    } catch (err) {
      message.error('加载技能失败：' + getErrorMessage(err))
    }
  }

  const loadMcp = async () => {
    try {
      setServers(await agentApi.mcpList())
    } catch (err) {
      message.error('加载 MCP 失败：' + getErrorMessage(err))
    }
  }

  const loadMemory = async () => {
    try {
      setMemFiles(await agentApi.memoryList())
    } catch (err) {
      message.error('加载记忆失败：' + getErrorMessage(err))
    }
  }

  useEffect(() => {
    loadSkills()
    loadMcp()
    loadMemory()
  }, [])

  // ---- Skill 操作 ----
  const submitSkill = async () => {
    try {
      const values = await skillForm.validateFields()
      const trigger_keyword = (values.trigger_keyword || '')
        .split(/[,，\n]/)
        .map((s: string) => s.trim())
        .filter(Boolean)
      await agentApi.skillRegister({ ...values, trigger_keyword })
      message.success('技能已注册')
      setSkillModal(false)
      skillForm.resetFields()
      loadSkills()
    } catch (err) {
      if ((err as any)?.errorFields) return
      message.error('注册失败：' + getErrorMessage(err))
    }
  }

  // ---- MCP 操作 ----
  const submitMcp = async () => {
    try {
      const values = await mcpForm.validateFields()
      await agentApi.mcpSave({
        ...values,
        args: (values.args || '')
          .split(/[\s,，\n]+/)
          .map((s: string) => s.trim())
          .filter(Boolean),
      })
      message.success('MCP 服务器已保存')
      setMcpModal(false)
      mcpForm.resetFields()
      loadMcp()
    } catch (err) {
      if ((err as any)?.errorFields) return
      message.error('保存失败：' + getErrorMessage(err))
    }
  }

  const testMcp = async (name: string) => {
    message.loading({ key: 'mcp-test', content: '正在测试…' })
    try {
      const res = await agentApi.mcpTest(name)
      if (res.ok) message.success({ key: 'mcp-test', content: `${name} 连接正常` })
      else message.error({ key: 'mcp-test', content: `${name}：${res.error}` })
    } catch (err) {
      message.error({ key: 'mcp-test', content: '测试失败：' + getErrorMessage(err) })
    }
  }

  // ---- Skill 上传 ----
  const skillUploadProps: UploadProps = {
    accept: '.md,.zip,.tar,.gz,.tgz,.py,.js,.ts,.json,.yaml,.yml',
    showUploadList: false,
    customRequest: async ({ file, onSuccess, onError }) => {
      try {
        const res = await agentApi.skillUpload(file as File)
        message.success(`上传成功，已注册 ${res.count} 个技能`)
        loadSkills()
        onSuccess?.(res)
      } catch (err) {
        message.error('上传失败：' + getErrorMessage(err))
        onError?.(err as Error)
      }
    },
  }

  // ---- GitHub 搜索 / 导入 ----
  const searchGithub = async (q?: string) => {
    const query = (q ?? githubQuery).trim() || 'agent skill SKILL.md'
    setGithubLoading(true)
    try {
      setGithubResults(await agentApi.githubSearch(query))
    } catch (err) {
      message.error('搜索失败：' + getErrorMessage(err))
    } finally {
      setGithubLoading(false)
    }
  }

  const importGithub = async (repoUrl: string) => {
    setImportingRepo(repoUrl)
    try {
      const res = await agentApi.githubImport(repoUrl)
      message.success(`导入成功，已注册 ${res.count} 个技能`)
      loadSkills()
    } catch (err) {
      message.error('导入失败：' + getErrorMessage(err))
    } finally {
      setImportingRepo(null)
    }
  }

  // ---- MCP 配置上传 ----
  const mcpUploadProps: UploadProps = {
    accept: '.json',
    showUploadList: false,
    customRequest: async ({ file, onSuccess, onError }) => {
      try {
        const res = await agentApi.mcpUpload(file as File)
        message.success(`上传成功，已注册 ${res.count} 个服务器`)
        loadMcp()
        onSuccess?.(res)
      } catch (err) {
        message.error('上传失败：' + getErrorMessage(err))
        onError?.(err as Error)
      }
    },
  }

  // ---- 记忆操作 ----
  const openMem = async (f: MemoryFile) => {
    try {
      const data = await agentApi.memoryGet(f.name)
      setMemView({ name: f.name, title: f.title, content: data.content })
      setMemDraft(data.content)
    } catch (err) {
      message.error('读取失败：' + getErrorMessage(err))
    }
  }

  const saveMem = async () => {
    if (!memView) return
    try {
      await agentApi.memoryWrite(memView.name, memDraft, false)
      message.success('记忆已保存')
      loadMemory()
    } catch (err) {
      message.error('保存失败：' + getErrorMessage(err))
    }
  }

  return (
    <div style={{ maxWidth: embedded ? 'none' : 1000, margin: '0 auto', padding: '16px 24px' }}>
      {!embedded && (
        <>
          <Title level={3} style={{ marginBottom: 4 }}>
            <ThunderboltOutlined /> 助手中心
          </Title>
          <Text type="secondary">配置全局助手的技能（Skill）、MCP 服务器与长期记忆</Text>
        </>
      )}

      <Tabs
        activeKey={tab}
        onChange={setTab}
        style={{ marginTop: 12 }}
        items={[
          {
            key: 'skills',
            label: (
              <Space>
                <ExperimentOutlined /> 技能 Skills
              </Space>
            ),
            children: (
              <Card>
                <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
                  <Text type="secondary">
                    技能（Skill）是助手可执行的工作流模板，命中触发词后自动调用。可注册、上传或从 GitHub 导入。
                  </Text>
                  <Space>
                    <Upload {...skillUploadProps}>
                      <Button icon={<UploadOutlined />}>上传 SKILL.md / 代码 / 压缩包</Button>
                    </Upload>
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => setSkillModal(true)}>
                      注册技能
                    </Button>
                  </Space>
                </div>

                {/* GitHub 搜索导入 */}
                <div style={{ background: '#fafafa', border: '1px dashed #d9d9d9', borderRadius: 8, padding: 12, marginBottom: 16 }}>
                  <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
                    <Space.Compact style={{ width: 420, maxWidth: '100%' }}>
                      <Input
                        prefix={<GithubOutlined />}
                        placeholder="搜索 GitHub 技能仓库，如：arxiv paper review"
                        value={githubQuery}
                        onChange={(e) => setGithubQuery(e.target.value)}
                        onPressEnter={() => searchGithub()}
                      />
                      <Button icon={<SearchOutlined />} loading={githubLoading} onClick={() => searchGithub()}>
                        搜索
                      </Button>
                    </Space.Compact>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      也可直接粘贴仓库地址到「导入」输入框
                    </Text>
                  </Space>

                  {githubResults.length > 0 && (
                    <>
                      <Divider style={{ margin: '12px 0 8px' }} />
                      <List
                        size="small"
                        dataSource={githubResults}
                        locale={{ emptyText: <Empty description="未找到仓库" /> }}
                        renderItem={(r) => (
                          <List.Item
                            actions={[
                              <Button
                                key="import"
                                size="small"
                                type="primary"
                                ghost
                                icon={importingRepo === r.html_url ? <Spin size="small" /> : <DownloadOutlined />}
                                disabled={!!importingRepo}
                                onClick={() => importGithub(r.html_url)}
                              >
                                {importingRepo === r.html_url ? '导入中…' : '导入'}
                              </Button>,
                            ]}
                          >
                            <List.Item.Meta
                              title={
                                <Space>
                                  <a href={r.html_url} target="_blank" rel="noreferrer" style={{ fontWeight: 600 }}>
                                    {r.full_name}
                                  </a>
                                  <Tag color="gold" style={{ fontSize: 11 }}>
                                    <StarOutlined /> {r.stars}
                                  </Tag>
                                  {r.language && <Tag>{r.language}</Tag>}
                                </Space>
                              }
                              description={
                                <Text type="secondary" ellipsis style={{ maxWidth: 520 }}>
                                  {r.description || '（无描述）'} · 更新于 {r.updated_at}
                                </Text>
                              }
                            />
                          </List.Item>
                        )}
                      />
                    </>
                  )}
                </div>
                {skills.length === 0 ? (
                  <Empty description="暂无技能" />
                ) : (
                  <List
                    dataSource={skills}
                    renderItem={(s) => (
                      <List.Item
                        actions={[
                          <Tooltip key="kw" title={(s.trigger_keyword || []).join('，')}>
                            <Tag color="blue">{(s.trigger_keyword || []).length} 个触发词</Tag>
                          </Tooltip>,
                          <Popconfirm
                            key="del"
                            title={`删除技能「${s.name}」？`}
                            onConfirm={async () => {
                              try {
                                await agentApi.skillRemove(s.name)
                                message.success('已删除')
                                loadSkills()
                              } catch (err) {
                                message.error(getErrorMessage(err))
                              }
                            }}
                          >
                            <Button danger size="small" icon={<DeleteOutlined />} />
                          </Popconfirm>,
                        ]}
                      >
                        <List.Item.Meta
                          title={
                            <Space>
                              {s.name}
                              <Tag color={s.category === 'custom' ? 'purple' : 'default'}>
                                {s.category}
                              </Tag>
                            </Space>
                          }
                          description={s.description || '（无描述）'}
                        />
                      </List.Item>
                    )}
                  />
                )}
              </Card>
            ),
          },
          {
            key: 'mcp',
            label: (
              <Space>
                <ApiOutlined /> MCP 服务器
              </Space>
            ),
            children: (
              <Card>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
                  <Text type="secondary">
                    MCP 服务器让助手接入外部工具与数据源（HTTP/SSE 或本地命令）。配置后可在对话中调用。
                  </Text>
                  <Button type="primary" icon={<PlusOutlined />} onClick={() => setMcpModal(true)}>
                    添加服务器
                  </Button>
                </div>
                {servers.length === 0 ? (
                  <Empty description="暂无 MCP 服务器" />
                ) : (
                  <Table
                    rowKey="name"
                    dataSource={servers}
                    pagination={false}
                    size="small"
                    columns={[
                      { title: '名称', dataIndex: 'name' },
                      {
                        title: '类型',
                        dataIndex: 'type',
                        render: (t) => <Tag color={t === 'stdio' ? 'geekblue' : 'green'}>{t}</Tag>,
                      },
                      {
                        title: '地址/命令',
                        render: (_, s) => (
                          <Text ellipsis style={{ maxWidth: 260 }}>
                            {s.type === 'http' ? s.url : `${s.command} ${(s.args || []).join(' ')}`}
                          </Text>
                        ),
                      },
                      {
                        title: '工具数',
                        render: (_, s) => (s.tools || []).length,
                      },
                      {
                        title: '操作',
                        render: (_, s) => (
                          <Space>
                            <Button size="small" onClick={() => testMcp(s.name)}>
                              测试
                            </Button>
                            <Popconfirm
                              title={`删除服务器「${s.name}」？`}
                              onConfirm={async () => {
                                try {
                                  await agentApi.mcpRemove(s.name)
                                  message.success('已删除')
                                  loadMcp()
                                } catch (err) {
                                  message.error(getErrorMessage(err))
                                }
                              }}
                            >
                              <Button danger size="small" icon={<DeleteOutlined />} />
                            </Popconfirm>
                          </Space>
                        ),
                      },
                    ]}
                  />
                )}
              </Card>
            ),
          },
          {
            key: 'memory',
            label: (
              <Space>
                <EyeOutlined /> 长期记忆
              </Space>
            ),
            children: (
              <Card>
                <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
                  长期记忆以本地 Markdown 文件保存，跨所有对话共享。助手会记住你的偏好，并随使用自动沉淀。
                </Text>
                <List
                  dataSource={memFiles}
                  renderItem={(f) => (
                    <List.Item
                      actions={[
                        <Button key="view" size="small" onClick={() => openMem(f)}>
                          查看/编辑
                        </Button>,
                      ]}
                    >
                      <List.Item.Meta
                        title={<Space>{f.title}</Space>}
                        description={
                          <Space direction="vertical" size={0}>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              更新于 {f.updated_at} · {f.size} 字节
                            </Text>
                            <Text type="secondary" ellipsis style={{ maxWidth: 480, fontSize: 12 }}>
                              {f.excerpt}
                            </Text>
                          </Space>
                        }
                      />
                    </List.Item>
                  )}
                />
              </Card>
            ),
          },
        ]}
      />

      {/* 注册技能弹窗 */}
      <Modal
        title="注册自定义技能"
        open={skillModal}
        onCancel={() => setSkillModal(false)}
        onOk={submitSkill}
        okText="注册"
        cancelText="取消"
      >
        <Form form={skillForm} layout="vertical">
          <Form.Item label="技能名称" name="name" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：my-research" />
          </Form.Item>
          <Form.Item label="描述" name="description">
            <Input placeholder="该技能做什么" />
          </Form.Item>
          <Form.Item label="触发关键词" name="trigger_keyword">
            <Input placeholder="用逗号分隔，如：综述,文献调研" />
          </Form.Item>
          <Form.Item label="分类" name="category" initialValue="custom">
            <Select
              options={[
                { value: 'custom', label: '自定义' },
                { value: 'literature', label: '文献' },
                { value: 'paper_writing', label: '写作' },
                { value: 'experiment_review', label: '实验' },
                { value: 'idea_evaluate', label: '选题' },
              ]}
            />
          </Form.Item>
          <Form.Item label="提示词模板（工作流/方法）" name="prompt_template">
            <TextArea rows={4} placeholder="指导助手如何执行该技能" />
          </Form.Item>
          <Form.Item label="约束规则" name="constraints">
            <TextArea rows={2} placeholder="输出格式等约束" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 添加 MCP 弹窗 */}
      <Modal
        title="添加 MCP 服务器"
        open={mcpModal}
        onCancel={() => setMcpModal(false)}
        onOk={submitMcp}
        okText="保存"
        cancelText="取消"
      >
        <Form form={mcpForm} layout="vertical">
          <Form.Item label="名称" name="name" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：github" />
          </Form.Item>
          <Form.Item label="类型" name="type" initialValue="http">
            <Select
              options={[
                { value: 'http', label: 'HTTP/SSE（远程）' },
                { value: 'stdio', label: 'stdio（本地命令）' },
              ]}
            />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(p, c) => p.type !== c.type}>
            {({ getFieldValue }) =>
              getFieldValue('type') === 'http' ? (
                <Form.Item label="URL" name="url">
                  <Input placeholder="https://mcp.example.com/sse" />
                </Form.Item>
              ) : (
                <>
                  <Form.Item label="命令" name="command">
                    <Input placeholder="如：npx" />
                  </Form.Item>
                  <Form.Item label="参数（空格分隔）" name="args">
                    <Input placeholder="如：-y @modelcontextprotocol/server-filesystem /tmp" />
                  </Form.Item>
                </>
              )
            }
          </Form.Item>
          <Form.Item label="描述" name="description">
            <Input placeholder="该服务器提供什么能力" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 记忆编辑弹窗 */}
      <Modal
        title={`编辑记忆 · ${memView?.title || ''}`}
        open={!!memView}
        onCancel={() => setMemView(null)}
        onOk={saveMem}
        okText="保存"
        cancelText="取消"
        width={640}
      >
        <TextArea
          value={memDraft}
          onChange={(e) => setMemDraft(e.target.value)}
          rows={12}
          style={{ fontFamily: 'monospace' }}
        />
        <Paragraph type="secondary" style={{ marginTop: 8, fontSize: 12 }}>
          这些内容会作为长期上下文注入给全局助手，并跨所有对话共享。
        </Paragraph>
      </Modal>
    </div>
  )
}
