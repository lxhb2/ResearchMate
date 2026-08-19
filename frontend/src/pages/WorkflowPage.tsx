import { useEffect, useMemo, lazy, Suspense, useState } from 'react'
import {
  Card,
  List,
  Button,
  Input,
  Typography,
  Empty,
  Spin,
  message,
  Space,
  Tag,
  Collapse,
  Divider,
  Alert,
  Form,
  Popconfirm,
} from 'antd'
import {
  PlayCircleOutlined,
  ThunderboltOutlined,
  FileTextOutlined,
  ApiOutlined,
  ArrowLeftOutlined,
  SaveOutlined,
  DeleteOutlined,
  PlusOutlined,
  AppstoreOutlined,
} from '@ant-design/icons'
import { workflowApi, type WorkflowTemplate, type WorkflowRunResult } from '../api/workflow'
import { getErrorMessage } from '../api/client'

// 白板依赖 React Flow，体积较大 → 懒加载，仅进入白板时加载，保持首屏轻量
const LazyWhiteboardView = lazy(() => import('../workflow/WhiteboardView'))
// 对话式执行界面（所有模板统一走这里）
import DialogueRunView from '../workflow/DialogueRunView'

const { TextArea } = Input
const { Text, Paragraph } = Typography

/** 自然语言生成：输入指令 → 生成工作流 → 保存为我的模板 */
function GenerateView({ onBack }: { onBack: () => void }) {
  const [prompt, setPrompt] = useState('')
  const [generating, setGenerating] = useState(false)
  const [workflowJson, setWorkflowJson] = useState<Record<string, any> | null>(null)
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveName, setSaveName] = useState('')

  const generate = async () => {
    if (!prompt.trim()) {
      message.warning('请输入科研指令')
      return
    }
    setGenerating(true)
    try {
      const res = await workflowApi.generate(prompt)
      setWorkflowJson(res.workflow_json)
      setDescription(res.description)
      setSaveName(res.workflow_json?.name || '我的自定义工作流')
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setGenerating(false)
    }
  }

  const saveAsTemplate = async () => {
    if (!workflowJson) return
    setSaving(true)
    try {
      await workflowApi.saveTemplate({
        name: saveName.trim() || '我的自定义工作流',
        description,
        workflow_json: workflowJson,
      })
      message.success('已保存为「我的模板」，可在模板库中选择运行')
      onBack()
    } catch (err) {
      message.error('保存失败：' + getErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <Button icon={<ArrowLeftOutlined />} style={{ marginBottom: 12 }} onClick={onBack}>
        返回模板库
      </Button>
      <Paragraph type="secondary">
        用一句话描述你的科研任务，AI 会把它拆解为可执行的工作流。确认结构后，可保存为「我的模板」以便下次直接运行。
      </Paragraph>
      <TextArea
        rows={3}
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder="例如：分析上周导入的 10 篇论文，提炼方法对比表，并写入我最近的写作项目"
      />
      <Space style={{ marginTop: 12 }}>
        <Button type="primary" icon={<ThunderboltOutlined />} loading={generating} onClick={generate}>
          生成工作流
        </Button>
      </Space>

      {description && (
        <>
          <Divider />
          <Alert type="info" showIcon message="任务拆解说明" description={description} />
        </>
      )}

      {workflowJson && (
        <>
          <Divider />
          <Text strong>
            <ApiOutlined /> 生成的工作流结构
          </Text>
          <pre
            style={{
              background: '#f6f8fa',
              padding: 12,
              borderRadius: 8,
              overflow: 'auto',
              maxHeight: 320,
              fontSize: 12,
            }}
          >
            {JSON.stringify(workflowJson, null, 2)}
          </pre>
          <Divider />
          <Space>
            <Text>模板名称：</Text>
            <Input
              style={{ width: 260 }}
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              placeholder="给这个模板起个名字"
            />
          </Space>
          <div style={{ marginTop: 12 }}>
            <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={saveAsTemplate}>
              保存为我的模板
            </Button>
          </div>
        </>
      )}
    </div>
  )
}

/** 模板选择中心：默认模板 + 我的自定义模板（运行），自然语言生成 / 白板式（创建） */
function LibraryView({
  templates,
  loading,
  onRun,
  onDelete,
  onGenerate,
  onWhiteboard,
}: {
  templates: WorkflowTemplate[]
  loading: boolean
  onRun: (tpl: WorkflowTemplate) => void
  onDelete: (tpl: WorkflowTemplate) => void
  onGenerate: () => void
  onWhiteboard: () => void
}) {
  const fixed = templates.filter((t) => t.source === 'fixed')
  const custom = templates.filter((t) => t.source === 'custom')

  const renderCard = (tpl: WorkflowTemplate) => (
    <Card
      key={tpl.workflow_id + tpl.id}
      title={
        <Space>
          <FileTextOutlined />
          {tpl.name}
        </Space>
      }
      extra={
        <Space>
          {tpl.editable && (
            <Popconfirm
              title="删除该模板？"
              onConfirm={() => onDelete(tpl)}
            >
              <Button size="small" icon={<DeleteOutlined />} danger>
                删除
              </Button>
            </Popconfirm>
          )}
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={() => onRun(tpl)}
          >
            运行
          </Button>
        </Space>
      }
    >
      <Paragraph type="secondary" style={{ minHeight: 32 }}>
        {tpl.description || '（无说明）'}
      </Paragraph>
      <Collapse
        ghost
        size="small"
        items={[
          {
            key: `${tpl.workflow_id}-nodes`,
            label: '查看节点结构',
            children: (
              <pre style={{ fontSize: 12, maxHeight: 240, overflow: 'auto' }}>
                {JSON.stringify(tpl.nodes, null, 2)}
              </pre>
            ),
          },
        ]}
      />
    </Card>
  )

  if (loading) return <Spin />
  if (!templates.length) return <Empty description="暂无可用模板" />

  return (
    <div>
      <Paragraph type="secondary">
        选择一个模板即可进入「对话式执行」：填写研究参数后自动顺着流程完成，需要你确认的地方会停下来等你。
      </Paragraph>

      <Divider orientation="left" plain>
        <Space>
          <AppstoreOutlined /> 运行模板
        </Space>
      </Divider>
      {fixed.length > 0 && (
        <>
          <Text strong>默认固定模板</Text>
          <List
            grid={{ gutter: 16, column: 1 }}
            dataSource={fixed}
            renderItem={renderCard}
            style={{ marginTop: 8 }}
          />
        </>
      )}
      {custom.length > 0 && (
        <>
          <Divider />
          <Text strong>我的自定义模板</Text>
          <List
            grid={{ gutter: 16, column: 1 }}
            dataSource={custom}
            renderItem={renderCard}
            style={{ marginTop: 8 }}
          />
        </>
      )}

      <Divider orientation="left" plain>
        <Space>
          <PlusOutlined /> 创建模板
        </Space>
      </Divider>
      <List
        grid={{ gutter: 16, column: 2 }}
        dataSource={[
          {
            key: 'nl',
            name: '自然语言生成',
            desc: '用一句话描述科研任务，AI 自动生成工作流并保存为模板',
            icon: <ThunderboltOutlined />,
            action: onGenerate,
          },
          {
            key: 'wb',
            name: '白板式拖拽',
            desc: '可视化拖拽节点搭建工作流，保存为模板使用',
            icon: <AppstoreOutlined />,
            action: onWhiteboard,
          },
        ]}
        renderItem={(item) => (
          <List.Item key={item.key}>
            <Card hoverable onClick={item.action}>
              <Space>
                {item.icon}
                <Text strong>{item.name}</Text>
              </Space>
              <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
                {item.desc}
              </Paragraph>
            </Card>
          </List.Item>
        )}
      />
    </div>
  )
}

export default function WorkflowPage() {
  const [view, setView] = useState<'library' | 'execute' | 'generate' | 'whiteboard'>('library')
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<WorkflowTemplate | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      setTemplates(await workflowApi.templates())
    } catch (err) {
      message.error(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const handleRun = (tpl: WorkflowTemplate) => {
    setSelected(tpl)
    setView('execute')
  }

  const handleDelete = async (tpl: WorkflowTemplate) => {
    try {
      await workflowApi.deleteTemplate(tpl.id)
      message.success('已删除')
      load()
    } catch (err) {
      message.error('删除失败：' + getErrorMessage(err))
    }
  }

  const handleWhiteboard = () => {
    setView('whiteboard')
  }

  const backToLibrary = () => {
    setView('library')
    load()
  }

  // 白板/运行视图占满内容区高度（内部各自滚动）；模板库/生成视图走自然流滚动
  const fullView = view === 'whiteboard' || view === 'execute'

  return (
    <div
      style={
        fullView
          ? { height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0 }
          : undefined
      }
    >
      <Typography.Title level={3} style={fullView ? { margin: '0 0 12px', flexShrink: 0 } : undefined}>
        Agent 工作流
      </Typography.Title>
      {view === 'library' && (
        <LibraryView
          templates={templates}
          loading={loading}
          onRun={handleRun}
          onDelete={handleDelete}
          onGenerate={() => setView('generate')}
          onWhiteboard={handleWhiteboard}
        />
      )}
      {view === 'execute' && selected && (
        <div style={{ flex: 1, minHeight: 0 }}>
          <DialogueRunView template={selected} onBack={backToLibrary} />
        </div>
      )}
      {view === 'generate' && <GenerateView onBack={backToLibrary} />}
      {view === 'whiteboard' && (
        <Suspense fallback={<Spin />}>
          <div style={{ flex: 1, minHeight: 0 }}>
            <LazyWhiteboardView onBack={backToLibrary} />
          </div>
        </Suspense>
      )}
    </div>
  )
}