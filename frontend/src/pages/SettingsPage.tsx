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
} from '@ant-design/icons'
import type { UploadProps } from 'antd'
import { Upload } from 'antd'
import {
  settingsApi,
  MODEL_PRESETS,
  COLOR_PRESETS,
  type AppSettings,
} from '../api/settings'
import { getErrorMessage, api } from '../api/client'
import { useThemeStore } from '../store/themeStore'

const { Title, Text, Paragraph } = Typography

export default function SettingsPage() {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [presetIdx, setPresetIdx] = useState<number | undefined>(undefined)
  const themeColor = useThemeStore((s) => s.color)
  const setThemeColor = useThemeStore((s) => s.setColor)
  const [pickedColor, setPickedColor] = useState(themeColor)

  useEffect(() => {
    let cancelled = false
    settingsApi
      .get()
      .then((cfg: AppSettings) => {
        if (cancelled) return
        form.setFieldsValue({
          llm_api_key: cfg.llm_api_key,
          llm_base_url: cfg.llm_base_url,
          llm_model: cfg.llm_model,
          embedding_model: cfg.embedding_model,
          embedding_dim: cfg.embedding_dim,
        })
        // 同步主题色
        const color = cfg.theme_color || themeColor
        setPickedColor(color)
        setThemeColor(color)
        // 匹配预设
        const idx = MODEL_PRESETS.findIndex((p) => p.base_url === cfg.llm_base_url)
        setPresetIdx(idx >= 0 ? idx : undefined)
      })
      .catch((err) => message.error('加载设置失败：' + getErrorMessage(err)))
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const onPresetChange = (idx: number) => {
    setPresetIdx(idx)
    const preset = MODEL_PRESETS[idx]
    if (preset) {
      form.setFieldsValue({
        llm_base_url: preset.base_url,
        llm_model: preset.models[0],
      })
    }
  }

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      const payload = {
        ...values,
        embedding_dim: Number(values.embedding_dim) || 1536,
        theme_color: pickedColor,
      }
      const updated = await settingsApi.update(payload)
      setThemeColor(pickedColor)
      form.setFieldsValue({ llm_api_key: updated.llm_api_key })
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
      const values = await form.validateFields(['llm_api_key', 'llm_base_url', 'llm_model'])
      const key = values.llm_api_key || ''
      // 如果是脱敏串（全是 *），不允许测试
      if (key && /^\*+$/.test(key)) {
        message.warning('请填写真实的 API Key 后再测试连接')
        return
      }
      setTesting(true)
      const res = await settingsApi.testConnection({
        api_key: key,
        base_url: values.llm_base_url,
        model: values.llm_model,
      })
      message.success(`连接成功，模型回复：${res.reply || '（空）'}`)
    } catch (err) {
      if ((err as any)?.errorFields) return
      message.error('连接测试失败：' + getErrorMessage(err))
    } finally {
      setTesting(false)
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
      <Text type="secondary">配置 AI 模型 API 与界面主题色</Text>

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
              options={MODEL_PRESETS.map((p, i) => ({
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
            label="API Key"
            name="llm_api_key"
            tooltip="从对应厂商的控制台获取，本地存储不上传第三方"
            rules={[{ required: true, message: '请填写 API Key' }]}
          >
            <Input.Password placeholder="sk-..." autoComplete="off" />
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

          {presetIdx !== undefined && MODEL_PRESETS[presetIdx]?.help && (
            <Paragraph type="secondary" style={{ marginTop: 4, marginBottom: 0 }}>
              <Tooltip title={MODEL_PRESETS[presetIdx]?.help}>
                <Tag bordered={false} color="blue">
                  {MODEL_PRESETS[presetIdx]?.name}
                </Tag>
              </Tooltip>
              {MODEL_PRESETS[presetIdx]?.help}
            </Paragraph>
          )}
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
    </div>
  )
}
