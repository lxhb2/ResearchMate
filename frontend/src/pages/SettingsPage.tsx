import { useEffect, useState } from 'react'
import {
  Card,
  Form,
  Input,
  Button,
  Select,
  ColorPicker,
  Space,
  Typography,
  Divider,
  Alert,
  Tag,
  Tooltip,
  InputNumber,
  Row,
  Col,
  message,
  Spin,
  Tabs,
} from 'antd'
import {
  ApiOutlined,
  CheckCircleOutlined,
  ThunderboltOutlined,
  BgColorsOutlined,
  ReloadOutlined,
  SaveOutlined,
  CloudDownloadOutlined,
  UploadOutlined,
  AppstoreOutlined,
  AppstoreAddOutlined,
  DeleteOutlined,
  GlobalOutlined,
} from '@ant-design/icons'
import type { UploadProps } from 'antd'
import { Upload, List, Switch, Popconfirm, Empty } from 'antd'
import AgentCenterPage from './AgentCenterPage'
import { agentApi, type PluginInfo } from '../api/agent'
import {
  settingsApi,
  MODEL_PRESETS,
  COLOR_PRESETS,
  type AppSettings,
  type ModelPreset,
  type SettingsUpdate,
} from '../api/settings'
import { getErrorMessage, api } from '../api/client'
import { useThemeStore } from '../store/themeStore'
import { appApi, type AppInfo, type UpdateCheckResult } from '../api/app'
import { fetchAppVersion } from '../utils/appVersion'

const { Title, Text, Paragraph } = Typography

const ACADEMIC_SOURCE_OPTIONS = [
  { value: 'openalex', label: 'OpenAlex' },
  { value: 'crossref', label: 'Crossref' },
  { value: 'europe_pmc', label: 'Europe PMC' },
  { value: 'semantic_scholar', label: 'Semantic Scholar' },
  { value: 'opencitations', label: 'OpenCitations' },
  { value: 'wikidata', label: 'WikiData' },
]

/** 插件生态面板：安装 zip 插件、启用/停用、卸载。 */
function PluginPanel() {
  const [plugins, setPlugins] = useState<PluginInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState('')

  const refresh = async () => {
    setLoading(true)
    try {
      setPlugins(await agentApi.pluginsList())
    } catch (err) {
      message.error('加载插件列表失败：' + getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleInstall: UploadProps['beforeUpload'] = async (file) => {
    setBusy('install')
    try {
      const res = await agentApi.pluginInstall(file)
      const n = (res?.skills?.length || 0) + (res?.tools?.length || 0) + (res?.mcp?.length || 0)
      message.success(`插件「${res?.name || file.name}」安装成功，已注册 ${n} 项能力`)
      await refresh()
    } catch (err) {
      message.error('安装失败：' + getErrorMessage(err))
    } finally {
      setBusy('')
    }
    return false
  }

  const toggle = async (p: PluginInfo, enabled: boolean) => {
    setBusy(p.name)
    try {
      if (enabled) await agentApi.pluginEnable(p.name)
      else await agentApi.pluginDisable(p.name)
      message.success(`插件「${p.display_name || p.name}」已${enabled ? '启用' : '停用'}`)
      await refresh()
    } catch (err) {
      message.error((enabled ? '启用' : '停用') + '失败：' + getErrorMessage(err))
    } finally {
      setBusy('')
    }
  }

  const uninstall = async (p: PluginInfo) => {
    setBusy(p.name)
    try {
      await agentApi.pluginUninstall(p.name)
      message.success(`插件「${p.display_name || p.name}」已卸载`)
      await refresh()
    } catch (err) {
      message.error('卸载失败：' + getErrorMessage(err))
    } finally {
      setBusy('')
    }
  }

  return (
    <>
      <Alert
        type="info"
        showIcon
        style={{ margin: '16px 0' }}
        message="插件生态"
        description="插件以 zip 包安装，可扩展技能（Skill）、工具与 MCP 服务器配置。插件目录结构：plugin.json 清单 + skills/ + tools/ + mcp.json。安装后立即激活，可随时停用或卸载。"
      />
      <Card
        title={
          <Space>
            <AppstoreAddOutlined />
            <span>安装插件</span>
          </Space>
        }
        style={{ marginBottom: 16 }}
        extra={
          <Upload accept=".zip" showUploadList={false} beforeUpload={handleInstall}>
            <Button type="primary" icon={<UploadOutlined />} loading={busy === 'install'}>
              上传插件 zip 安装
            </Button>
          </Upload>
        }
      >
        <List
          loading={loading}
          dataSource={plugins}
          locale={{ emptyText: <Empty description="暂未安装插件" /> }}
          renderItem={(p) => (
            <List.Item
              actions={[
                <Switch
                  key="switch"
                  size="small"
                  checked={!!p.active}
                  loading={busy === p.name}
                  disabled={!p.valid}
                  onChange={(checked) => toggle(p, checked)}
                />,
                <Popconfirm
                  key="del"
                  title="确认卸载该插件？"
                  description="将同时移除其注册的技能 / 工具 / MCP 配置"
                  onConfirm={() => uninstall(p)}
                >
                  <Button size="small" danger icon={<DeleteOutlined />} loading={busy === p.name}>
                    卸载
                  </Button>
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space size={8} wrap>
                    <span>{p.display_name || p.name}</span>
                    {p.version && <Tag bordered={false}>v{p.version}</Tag>}
                    {p.valid ? (
                      p.active ? (
                        <Tag color="success" bordered={false}>
                          已激活
                        </Tag>
                      ) : (
                        <Tag bordered={false}>未激活</Tag>
                      )
                    ) : (
                      <Tag color="error" bordered={false}>
                        清单无效
                      </Tag>
                    )}
                  </Space>
                }
                description={
                  <Space direction="vertical" size={2}>
                    <Text type="secondary">{p.description || p.error || '（无描述）'}</Text>
                    {(p.skills?.length || p.tools?.length || p.mcp_servers?.length) && (
                      <Space size={6} wrap>
                        {!!p.skills?.length && (
                          <Tag color="blue" bordered={false}>
                            技能 × {p.skills.length}
                          </Tag>
                        )}
                        {!!p.tools?.length && (
                          <Tag color="purple" bordered={false}>
                            工具 × {p.tools.length}
                          </Tag>
                        )}
                        {!!p.mcp_servers?.length && (
                          <Tag color="cyan" bordered={false}>
                            MCP × {p.mcp_servers.length}
                          </Tag>
                        )}
                      </Space>
                    )}
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      </Card>
    </>
  )
}

/** 版本与更新面板：Web 模式跳 GitHub Releases，Electron 模式可原生下载安装。 */
function UpdatePanel() {
  const [info, setInfo] = useState<AppInfo | null>(null)
  const [versionText, setVersionText] = useState('')
  const [update, setUpdate] = useState<UpdateCheckResult | null>(null)
  const [checking, setChecking] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [installing, setInstalling] = useState(false)
  const native = window.researchmate

  useEffect(() => {
    let cancelled = false
    appApi
      .info()
      .then((i) => {
        if (cancelled) return
        setInfo(i)
        setVersionText(i.version)
      })
      .catch(() => setInfo(null))
    fetchAppVersion().then((v) => {
      if (!cancelled && v) setVersionText(v)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const check = async () => {
    setChecking(true)
    try {
      const result = await appApi.checkUpdate()
      setUpdate(result)
      if (result.current) setVersionText(result.current)
    } catch (err) {
      message.error('检查更新失败：' + getErrorMessage(err))
    } finally {
      setChecking(false)
    }
  }

  const download = async () => {
    if (!native) return
    setDownloading(true)
    try {
      const res = await native.downloadUpdate()
      if (res.ok) message.success('更新包已下载，可点击“安装更新”')
      else message.error('下载失败：' + (res.error || '未知错误'))
    } finally {
      setDownloading(false)
    }
  }

  const install = async () => {
    if (!native) return
    setInstalling(true)
    const res = await native.installUpdate()
    if (!res.ok) message.error('安装失败：' + (res.error || '未知错误'))
    setInstalling(false)
  }

  return (
    <Card
      title={
        <Space>
          <CloudDownloadOutlined style={{ color: '#2563eb' }} />
          <span>版本与更新</span>
        </Space>
      }
      style={{ marginBottom: 16 }}
    >
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Space wrap align="center">
          <Tag color="blue" bordered={false}>
            ResearchMate v{info?.version || versionText || '加载中'}
          </Tag>
          <Text type="secondary">
            {info?.repo ? `GitHub: ${info.repo}` : '本地单机版'}
          </Text>
          <Button icon={<ReloadOutlined />} loading={checking} onClick={check}>
            检查更新
          </Button>
          {info?.update_url && (
            <Button href={info.update_url} target="_blank">
              打开 Releases 页面
            </Button>
          )}
        </Space>

        {update && (
          <div
            style={{
              padding: '10px 12px',
              borderRadius: 8,
              border: update.has_update ? '1px solid #bfdbfe' : '1px solid #d1fae5',
              background: update.has_update ? '#eff6ff' : '#ecfdf5',
            }}
          >
            {update.has_update ? (
              <>
                <Space wrap align="center">
                  <Tag color="processing" bordered={false}>
                    发现新版本 v{update.latest}
                  </Tag>
                  <Text type="secondary">当前 v{update.current}</Text>
                  {update.release_name && <Text strong>{update.release_name}</Text>}
                </Space>
                <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <Button href={update.release_url} target="_blank">
                    查看发布说明
                  </Button>
                  {native && (
                    <>
                      <Button
                        type="primary"
                        icon={<CloudDownloadOutlined />}
                        loading={downloading}
                        onClick={download}
                      >
                        下载更新
                      </Button>
                      <Button
                        icon={<CheckCircleOutlined />}
                        loading={installing}
                        onClick={install}
                      >
                        安装更新
                      </Button>
                    </>
                  )}
                </div>
                {update.assets.length > 0 && (
                  <Space size={[6, 6]} wrap style={{ marginTop: 8 }}>
                    {update.assets.slice(0, 5).map((a) => (
                      <Tag key={a.name} bordered={false}>
                        <a href={a.url} target="_blank" rel="noreferrer">
                          {a.name}
                        </a>
                      </Tag>
                    ))}
                  </Space>
                )}
              </>
            ) : (
              <Space>
                <CheckCircleOutlined style={{ color: '#16a34a' }} />
                <Text>当前已是最新版本（v{update.current}）。</Text>
              </Space>
            )}
          </div>
        )}

        {!update && (
          <Text type="secondary">
            版本检查通过 GitHub Releases 完成。首次发布后，应用内即可检测到新版本。
          </Text>
        )}
      </Space>
    </Card>
  )
}

export default function SettingsPage() {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [presetIdx, setPresetIdx] = useState<number | undefined>(undefined)
  const [presets, setPresets] = useState<ModelPreset[]>(MODEL_PRESETS)
  const themeColor = useThemeStore((s) => s.color)
  const setThemeColor = useThemeStore((s) => s.setColor)
  const [pickedColor, setPickedColor] = useState(themeColor)
  // 已保存 Key 的脱敏展示（如 sk-1****abcd）与是否已配置
  const [keyMasked, setKeyMasked] = useState('')
  const [keyConfigured, setKeyConfigured] = useState(false)
  const [searchKeyMasked, setSearchKeyMasked] = useState('')
  const [searchKeyConfigured, setSearchKeyConfigured] = useState(false)
  const [agentKeyMasked, setAgentKeyMasked] = useState('')
  const [agentKeyConfigured, setAgentKeyConfigured] = useState(false)
  const [searchTesting, setSearchTesting] = useState(false)

  // 尝试从后端拉取模型预设，失败则使用前端兜底列表
  useEffect(() => {
    let cancelled = false
    settingsApi
      .getModelPresets()
      .then((list) => {
        if (!cancelled && list && list.length > 0) {
          setPresets(list)
        }
      })
      .catch(() => {
        // 静默失败：前端 MODEL_PRESETS 已作为兜底
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    settingsApi
      .get()
      .then((cfg: AppSettings) => {
        if (cancelled) return
        // Key 不回填到输入框（防止把脱敏串误存回库）：
        // - 已配置：占位符展示脱敏值，输入框留空 = 保持不变
        // - 未配置：提示输入新 Key
        setKeyMasked(cfg.llm_api_key || '')
        setKeyConfigured(!!(cfg.llm_api_key && cfg.llm_api_key.trim()))
        setSearchKeyMasked(cfg.anysearch_api_key || '')
        setSearchKeyConfigured(!!(cfg.anysearch_api_key && cfg.anysearch_api_key.trim()))
        setAgentKeyMasked(cfg.agentsearch_token || '')
        setAgentKeyConfigured(!!(cfg.agentsearch_token && cfg.agentsearch_token.trim()))
        form.setFieldsValue({
          llm_api_key: '',
          llm_base_url: cfg.llm_base_url,
          llm_model: cfg.llm_model,
          embedding_model: cfg.embedding_model,
          embedding_dim: cfg.embedding_dim,
          anysearch_enabled: cfg.anysearch_enabled,
          anysearch_api_key: '',
          anysearch_base_url: cfg.anysearch_base_url,
          searxng_url: cfg.searxng_url,
          agentsearch_url: cfg.agentsearch_url,
          agentsearch_token: '',
          agentsearch_mode: cfg.agentsearch_mode || 'general',
          academic_sources: cfg.academic_sources || [
            'openalex',
            'crossref',
            'europe_pmc',
            'semantic_scholar',
          ],
        })
        // 同步主题色
        const color = cfg.theme_color || themeColor
        setPickedColor(color)
        setThemeColor(color)
        // 匹配预设：优先同时命中 base_url + model；否则仅命中 base_url
        const exactIdx = presets.findIndex(
          (p) => p.base_url === cfg.llm_base_url && p.models.includes(cfg.llm_model || '')
        )
        const fuzzyIdx = presets.findIndex((p) => p.base_url === cfg.llm_base_url)
        setPresetIdx(exactIdx >= 0 ? exactIdx : fuzzyIdx >= 0 ? fuzzyIdx : undefined)
      })
      .catch((err) => message.error('加载设置失败：' + getErrorMessage(err)))
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presets])

  const onPresetChange = (idx: number) => {
    setPresetIdx(idx)
    const preset = presets[idx]
    if (preset) {
      const updates: Record<string, string> = {
        llm_base_url: preset.base_url,
        llm_model: preset.models[0] || '',
      }
      // 若该预设推荐了 embedding 模型且当前未填写，则一并填充
      const currentEmbedding = form.getFieldValue('embedding_model') as string
      if (preset.embedding_model && !currentEmbedding?.trim()) {
        updates.embedding_model = preset.embedding_model
      }
      form.setFieldsValue(updates)
    }
  }

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      const payload: Record<string, unknown> = {
        ...values,
        embedding_dim: Number(values.embedding_dim) || 1536,
        theme_color: pickedColor,
      }
      // Key 留空 = 保持已保存的 Key 不变（后端也不会接受含 * 的值）
      const newKey = (values.llm_api_key || '').trim()
      if (newKey) {
        payload.llm_api_key = newKey
      } else {
        delete payload.llm_api_key
      }
      const newSearchKey = (values.anysearch_api_key || '').trim()
      if (newSearchKey) {
        payload.anysearch_api_key = newSearchKey
      } else {
        delete payload.anysearch_api_key
      }
      const newAgentKey = (values.agentsearch_token || '').trim()
      if (newAgentKey) {
        payload.agentsearch_token = newAgentKey
      } else {
        delete payload.agentsearch_token
      }
      const updated = await settingsApi.update(payload)
      setThemeColor(pickedColor)
      // 保存后 Key 输入框清空，占位符换为新脱敏值
      form.setFieldsValue({ llm_api_key: '' })
      setKeyMasked(updated.llm_api_key || '')
      setKeyConfigured(!!updated.llm_api_key?.trim())
      form.setFieldsValue({ anysearch_api_key: '' })
      setSearchKeyMasked(updated.anysearch_api_key || '')
      setSearchKeyConfigured(!!updated.anysearch_api_key?.trim())
      form.setFieldsValue({ agentsearch_token: '' })
      setAgentKeyMasked(updated.agentsearch_token || '')
      setAgentKeyConfigured(!!updated.agentsearch_token?.trim())
      message.success('设置已保存')
    } catch (err) {
      if ((err as any)?.errorFields) return // form validation error
      message.error('保存失败：' + getErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    try {
      const values = await form.validateFields(['llm_base_url', 'llm_model'])
      const key = (form.getFieldValue('llm_api_key') || '').trim()
      // Key 留空且已有保存的 Key：后端会自动使用已保存的 Key 测试
      if (!key && !keyConfigured) {
        message.warning('请填写 API Key 后再测试连接')
        return
      }
      setTesting(true)
      const res = await settingsApi.testConnection({
        api_key: key,
        base_url: values.llm_base_url,
        model: values.llm_model,
      })
      // 测试通过后顺手保存，避免“填了 Key 但页面仍提示未配置”。
      const savePayload: SettingsUpdate = {
        llm_base_url: values.llm_base_url,
        llm_model: values.llm_model,
        embedding_model: (form.getFieldValue('embedding_model') as string) || '',
        embedding_dim: Number(form.getFieldValue('embedding_dim')) || 1536,
        theme_color: pickedColor,
      }
      if (key) {
        savePayload.llm_api_key = key
      }
      const updated = await settingsApi.update(savePayload)
      form.setFieldsValue({ llm_api_key: '' })
      setKeyMasked(updated.llm_api_key || '')
      setKeyConfigured(!!updated.llm_api_key?.trim())
      message.success(`连接成功，配置已保存，模型回复：${res.reply || '（空）'}`)
    } catch (err) {
      if ((err as any)?.errorFields) return
      message.error('连接测试失败：' + getErrorMessage(err))
    } finally {
      setTesting(false)
    }
  }

  const handleTestSearch = async () => {
    try {
      const values = await form.validateFields([
        'anysearch_base_url',
        'searxng_url',
        'agentsearch_url',
        'agentsearch_mode',
      ])
      const newKey = (form.getFieldValue('anysearch_api_key') || '').trim()
      const newAgentToken = (form.getFieldValue('agentsearch_token') || '').trim()
      setSearchTesting(true)
      const res = await settingsApi.testSearch({
        provider: 'auto',
        anysearch_api_key: newKey || undefined,
        anysearch_base_url: values.anysearch_base_url,
        searxng_url: values.searxng_url,
        agentsearch_url: values.agentsearch_url,
        agentsearch_token: newAgentToken || undefined,
        agentsearch_mode: values.agentsearch_mode,
      })
      message.success(`搜索连接正常：${res.engine}（返回 ${res.count} 条结果）`)
    } catch (err) {
      message.error('搜索测试失败：' + getErrorMessage(err))
    } finally {
      setSearchTesting(false)
    }
  }

  const applyThemePreview = (color: string) => {
    setPickedColor(color)
    setThemeColor(color) // 实时预览
  }

  const handleRestore: UploadProps['beforeUpload'] = async (file) => {
    const form = new FormData()
    form.append('file', file)
    try {
      message.loading({ key: 'restoring', content: '正在恢复，请稍候…' })
      const { data } = await api.post('/backup/restore', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      message.success({ key: 'restoring', content: data?.message || '恢复成功' })
    } catch (err) {
      message.error({ key: 'restoring', content: '恢复失败：' + getErrorMessage(err) })
    }
    return false // 阻止默认上传
  }

  if (loading) {
    return (
      <div style={{ padding: 48, textAlign: 'center' }}>
        <Spin tip="加载设置中…" />
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 880, margin: '0 auto', padding: '16px 24px' }}>
      <Title level={3} style={{ marginBottom: 4 }}>
        <ApiOutlined /> 设置
      </Title>
      <Text type="secondary">配置 AI 模型 API、联网搜索、界面主题色，以及全局助手的技能 / MCP / 长期记忆</Text>

      <Tabs
        style={{ marginTop: 8 }}
        items={[
          {
            key: 'model',
            label: (
              <Space>
                <ApiOutlined /> 模型与主题
              </Space>
            ),
            children: (
              <>
                <Alert
                  type="info"
                  showIcon
                  style={{ margin: '16px 0' }}
                  message="OpenAI 兼容接口"
                  description="本应用支持所有 OpenAI 协议兼容的国内大模型（通义千问、智谱 GLM、DeepSeek、Kimi、文心一言、豆包、星火等），填入对应厂商的 base_url、API Key 与模型名即可。"
                />

      {/* LLM API 配置 */}
      <Card
        title={
          <Space>
            <ApiOutlined style={{ color: themeColor }} />
            <span>聊天 AI API 配置</span>
          </Space>
        }
        style={{ marginBottom: 16 }}
        extra={
          <Tag icon={<CheckCircleOutlined />} color="processing">
            OpenAI 兼容
          </Tag>
        }
      >
        <Form form={form} layout="vertical" requiredMark={false}>
          <Form.Item label="国内大模型预设">
            <Select
              placeholder="选择预设可一键填充 base_url 与模型名"
              value={presetIdx}
              onChange={onPresetChange}
              allowClear
              options={presets.map((p, i) => ({
                value: i,
                label: `${p.name}  ·  ${p.base_url}`,
              }))}
            />
          </Form.Item>

          <Form.Item
            label="API Base URL"
            name="llm_base_url"
            tooltip="OpenAI 兼容接口的根地址，例如 https://dashscope.aliyuncs.com/compatible-mode/v1"
            rules={[{ required: true, message: '请填写 Base URL' }]}
          >
            <Input placeholder="https://api.example.com/v1" autoComplete="off" />
          </Form.Item>

          <Form.Item
            label={
              <Space size={6}>
                <span>API Key</span>
                {keyConfigured && (
                  <Tag bordered={false} color="success" style={{ marginInlineEnd: 0 }}>
                    已配置 {keyMasked}
                  </Tag>
                )}
              </Space>
            }
            name="llm_api_key"
            tooltip="从对应厂商的控制台获取，本地存储不上传第三方。出于安全不会回显已保存的 Key；留空保存即保持现有 Key 不变"
          >
            <Input.Password
              placeholder={keyConfigured ? `已保存（${keyMasked}），留空保持不变；输入新 Key 可替换` : 'sk-...'}
              autoComplete="new-password"
            />
          </Form.Item>

          <Form.Item
            label="聊天模型名称"
            name="llm_model"
            tooltip="厂商支持的模型 ID，例如 qwen-plus、glm-4-flash、deepseek-chat"
            rules={[{ required: true, message: '请填写模型名称' }]}
          >
            <Input placeholder="qwen-plus" />
          </Form.Item>

          <Space style={{ marginBottom: 8 }}>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={testing}
              onClick={handleTest}
            >
              测试连接
            </Button>
          </Space>

          {presetIdx !== undefined && presets[presetIdx]?.help && (
            <Paragraph type="secondary" style={{ marginTop: 4, marginBottom: 0 }}>
              <Tooltip title={presets[presetIdx]?.help}>
                <Tag bordered={false} color="blue">
                  {presets[presetIdx]?.name}
                </Tag>
              </Tooltip>
              {presets[presetIdx]?.help}
            </Paragraph>
          )}
        </Form>
      </Card>

      {/* 联网搜索 API 配置 */}
      <Card
        title={
          <Space>
            <GlobalOutlined style={{ color: themeColor }} />
            <span>联网搜索 API 配置</span>
          </Space>
        }
        style={{ marginBottom: 16 }}
        extra={
          <Tag color="blue" bordered={false}>
            AnySearch / SearXNG / AgentSearch
          </Tag>
        }
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="搜索默认调用 AnySearch 公开 API"
          description="AnySearch 匿名可用，无需 Key；搜索关键词会发送到 api.anysearch.com。如需完全本地化，可配置自建 SearXNG 或 AgentSearch 地址，配置后会优先使用自建服务。敏感数据场景请关闭 AnySearch。"
        />
        <Form form={form} layout="vertical" requiredMark={false}>
          <Form.Item
            label="启用 AnySearch"
            name="anysearch_enabled"
            valuePropName="checked"
            tooltip="关闭后仅使用 SearXNG 或 Bing/DuckDuckGo 兜底"
          >
            <Switch />
          </Form.Item>
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item
                label={
                  <Space size={6}>
                    <span>AnySearch API Key（可选）</span>
                    {searchKeyConfigured && (
                      <Tag bordered={false} color="success" style={{ marginInlineEnd: 0 }}>
                        已配置 {searchKeyMasked}
                      </Tag>
                    )}
                  </Space>
                }
                name="anysearch_api_key"
                tooltip="到 anysearch.com/console/api-keys 免费创建；留空保存即保持现有 Key 不变"
              >
                <Input.Password
                  placeholder={searchKeyConfigured ? `已保存（${searchKeyMasked}），留空保持不变` : '可选，留空使用匿名访问'}
                  autoComplete="new-password"
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label="AnySearch Base URL" name="anysearch_base_url">
                <Input placeholder="https://api.anysearch.com" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            label="SearXNG 地址（可选，自建开源替代）"
            name="searxng_url"
            tooltip="例如 http://localhost:8888；配置后搜索会优先走自建 SearXNG"
          >
            <Input placeholder="http://localhost:8888" />
          </Form.Item>
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item
                label="AgentSearch 地址（可选，自建搜索+取证）"
                name="agentsearch_url"
                tooltip="例如 http://localhost:3939；配置后搜索会优先走自建 AgentSearch"
              >
                <Input placeholder="http://localhost:3939" />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item
                label={
                  <Space size={6}>
                    <span>AgentSearch Token（可选）</span>
                    {agentKeyConfigured && (
                      <Tag bordered={false} color="success" style={{ marginInlineEnd: 0 }}>
                        已配置 {agentKeyMasked}
                      </Tag>
                    )}
                  </Space>
                }
                name="agentsearch_token"
                tooltip="自建 AgentSearch 启用鉴权时填写；留空保存即保持现有 Token 不变"
              >
                <Input.Password
                  placeholder={agentKeyConfigured ? `已保存（${agentKeyMasked}），留空保持不变` : '可选'}
                  autoComplete="new-password"
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="AgentSearch 检索模式" name="agentsearch_mode">
            <Select
              options={[
                { value: 'general', label: 'general（通用）' },
                { value: 'academic', label: 'academic（学术）' },
                { value: 'code', label: 'code（代码）' },
                { value: 'news', label: 'news（新闻）' },
              ]}
            />
          </Form.Item>
          <Form.Item
            label="学术搜索数据源（可多选）"
            name="academic_sources"
            tooltip="学术查询只会并行调用这里选中的源；OpenCitations 适合 DOI 精确查询，WikiData 适合实体与概念溯源"
            rules={[{ required: true, message: '请至少选择一个学术源' }]}
          >
            <Select
              mode="multiple"
              placeholder="至少选择一个学术源"
              maxTagCount="responsive"
              options={ACADEMIC_SOURCE_OPTIONS}
            />
          </Form.Item>
          <Space>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={searchTesting}
              onClick={handleTestSearch}
            >
              测试搜索连接
            </Button>
            <Text type="secondary">测试会实际请求一次搜索接口，验证 Key 与地址是否可用。</Text>
          </Space>
        </Form>
      </Card>

      {/* Embedding 配置 */}
      <Card
        title={
          <Space>
            <ApiOutlined style={{ color: themeColor }} />
            <span>向量嵌入模型（用于语义检索）</span>
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        <Form form={form} layout="vertical" requiredMark={false}>
          <Row gutter={16}>
            <Col xs={24} md={16}>
              <Form.Item
                label="Embedding 模型名称"
                name="embedding_model"
                tooltip="通常与 LLM 同厂商，例如 text-embedding-v3、bge-large-zh"
              >
                <Input placeholder="text-embedding-v3" />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="向量维度" name="embedding_dim">
                <InputNumber
                  min={64}
                  max={8192}
                  step={64}
                  style={{ width: '100%' }}
                  placeholder="1536"
                />
              </Form.Item>
            </Col>
          </Row>
          <Text type="secondary">
            提示：上传文献的语义检索依赖嵌入模型；若厂商未提供 embedding 接口，可留空使用默认行为。
          </Text>
        </Form>
      </Card>

      {/* 主题色个性化 */}
      <Card
        title={
          <Space>
            <BgColorsOutlined style={{ color: themeColor }} />
            <span>界面主题色</span>
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        <Paragraph type="secondary">选择预设色或自定义颜色，修改即时生效。</Paragraph>
        <Space size={[12, 12]} wrap style={{ marginBottom: 16 }}>
          {COLOR_PRESETS.map((c) => {
            const active = pickedColor.toLowerCase() === c.color.toLowerCase()
            return (
              <Tooltip key={c.color} title={c.name}>
                <div
                  onClick={() => applyThemePreview(c.color)}
                  style={{
                    width: 36,
                    height: 36,
                    borderRadius: 8,
                    background: c.color,
                    cursor: 'pointer',
                    border: active ? '3px solid #000' : '2px solid #eee',
                    boxShadow: active ? '0 0 0 3px rgba(0,0,0,0.1)' : 'none',
                  }}
                />
              </Tooltip>
            )
          })}
        </Space>
        <Divider style={{ margin: '12px 0' }} />
        <Space align="center" wrap>
          <Text>自定义：</Text>
          <ColorPicker
            value={pickedColor}
            onChange={(c) => applyThemePreview(c.toHexString())}
            showText
            format="hex"
          />
          <Button
            icon={<ReloadOutlined />}
            onClick={() => applyThemePreview('#4f46e5')}
          >
            重置默认
          </Button>
        </Space>
      </Card>

      {/* 数据备份恢复 */}
      <Card
        title={
          <Space>
            <CloudDownloadOutlined style={{ color: themeColor }} />
            <span>数据备份与恢复</span>
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        <Paragraph type="secondary">
          所有数据本地保存（SQLite 数据库 + PDF 文件）。可一键导出为 zip 备份到本地，或从备份恢复。适合无云盘、无服务器的本地使用场景。
        </Paragraph>
        <Space wrap>
          <a href="/api/v1/backup/export">
            <Button icon={<CloudDownloadOutlined />}>导出备份 (zip)</Button>
          </a>
          <Upload
            accept=".zip"
            showUploadList={false}
            beforeUpload={handleRestore}
          >
            <Button icon={<UploadOutlined />}>恢复备份</Button>
          </Upload>
        </Space>
      </Card>

      <div style={{ textAlign: 'right' }}>
        <Button
          type="primary"
          size="large"
          icon={<SaveOutlined />}
          loading={saving}
          onClick={handleSave}
        >
          保存设置
        </Button>
      </div>
              </>
            ),
          },
          {
            key: 'agent',
            label: (
              <Space>
                <ThunderboltOutlined /> 助手中心
              </Space>
            ),
            children: <AgentCenterPage embedded />,
          },
          {
            key: 'plugins',
            label: (
              <Space>
                <AppstoreOutlined /> 插件
              </Space>
            ),
            children: <PluginPanel />,
          },
          {
            key: 'update',
            label: (
              <Space>
                <CloudDownloadOutlined /> 版本与更新
              </Space>
            ),
            children: <UpdatePanel />,
          },
        ]}
      />
    </div>
  )
}
