import { api } from './client'

export interface AppSettings {
  llm_api_key: string
  llm_base_url: string
  llm_model: string
  embedding_model: string
  embedding_dim: number
  theme_color: string
}

export interface SettingsUpdate {
  llm_api_key?: string
  llm_base_url?: string
  llm_model?: string
  embedding_model?: string
  embedding_dim?: number
  theme_color?: string
}

export interface TestConnectionPayload {
  api_key: string
  base_url: string
  model: string
}

export const settingsApi = {
  get: () => api.get<AppSettings>('/settings').then((r) => r.data),
  update: (payload: SettingsUpdate) =>
    api.put<AppSettings>('/settings', payload).then((r) => r.data),
  testConnection: (payload: TestConnectionPayload) =>
    api.post<{ ok: boolean; reply: string }>('/settings/test-connection', payload).then((r) => r.data),
}

// 国内主流大模型 OpenAI 兼容接口预设
export interface ModelPreset {
  name: string
  base_url: string
  models: string[]
  help?: string
}

export const MODEL_PRESETS: ModelPreset[] = [
  {
    name: '通义千问 (DashScope)',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: ['qwen-plus', 'qwen-max', 'qwen-turbo', 'qwen2.5-72b-instruct', 'qwen2.5-7b-instruct'],
    help: '阿里云百炼，兼容 OpenAI 协议，model 推荐用 qwen-plus / qwen-max',
  },
  {
    name: '智谱 AI (BigModel)',
    base_url: 'https://open.bigmodel.cn/api/paas/v4',
    models: ['glm-4-plus', 'glm-4', 'glm-4-air', 'glm-4-flash', 'glm-4-flashx'],
    help: '智谱 GLM 系列，glm-4-flash 免费可用',
  },
  {
    name: 'DeepSeek',
    base_url: 'https://api.deepseek.com/v1',
    models: ['deepseek-chat', 'deepseek-reasoner', 'deepseek-coder'],
    help: 'DeepSeek 官方 API，价格友好，推理能力强',
  },
  {
    name: 'Moonshot (Kimi)',
    base_url: 'https://api.moonshot.cn/v1',
    models: ['moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k', 'kimi-latest'],
    help: 'Kimi 长上下文模型，128k 适合长文献',
  },
  {
    name: '月之暗面 (Moonshot)',
    base_url: 'https://api.moonshot.cn/v1',
    models: ['moonshot-v1-8k', 'moonshot-v1-32k'],
  },
  {
    name: '百度千帆 (兼容模式)',
    base_url: 'https://qianfan.baidubce.com/v2',
    models: ['ernie-4.0-8k-latest', 'ernie-3.5-8k', 'ernie-speed-128k', 'ernie-lite-8k'],
    help: '百度千帆 v2 OpenAI 兼容接口',
  },
  {
    name: '讯飞星火',
    base_url: 'https://spark-api-open.xf-yun.com/v1',
    models: ['generalv3.5', 'general', 'spark-v4'],
    help: '讯飞星火 OpenAI 兼容接口',
  },
  {
    name: 'MiniMax',
    base_url: 'https://api.minimax.chat/v1',
    models: ['abab6.5s-chat', 'abab6.5-chat', 'abab6-chat'],
    help: 'MiniMax 开放平台',
  },
  {
    name: '字节豆包 (VolcEngine)',
    base_url: 'https://ark.cn-beijing.volces.com/api/v3',
    models: ['doubao-pro-32k', 'doubao-pro-128k', 'doubao-lite-32k'],
    help: '火山方舟，需在控制台创建接入点 ID 作为 model',
  },
  {
    name: '零一万物 (01.AI)',
    base_url: 'https://api.lingyiwanwu.com/v1',
    models: ['yi-large', 'yi-medium', 'yi-lightning', 'yi-vision'],
    help: '零一万物 Yi 系列',
  },
  {
    name: '阶跃星辰 (Step)',
    base_url: 'https://api.stepfun.com/v1',
    models: ['step-1-8k', 'step-1-32k', 'step-1-128k', 'step-2-16k'],
    help: 'Step 系列模型',
  },
  {
    name: 'OpenAI / Azure OpenAI',
    base_url: 'https://api.openai.com/v1',
    models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4.1-mini', 'o1-mini'],
    help: '官方 OpenAI 或自建代理',
  },
  {
    name: '本地 / Ollama',
    base_url: 'http://localhost:11434/v1',
    models: ['llama3.1', 'qwen2.5', 'deepseek-r1', 'phi3'],
    help: '本地部署的 Ollama，无需 API Key 可填任意字符串',
  },
]

// 主题色预设
export interface ColorPreset {
  name: string
  color: string
}

export const COLOR_PRESETS: ColorPreset[] = [
  { name: '靛蓝', color: '#4f46e5' },
  { name: '极客蓝', color: '#1677ff' },
  { name: '翡翠绿', color: '#10b981' },
  { name: '日落橙', color: '#f97316' },
  { name: '玫瑰红', color: '#e11d48' },
  { name: '紫罗兰', color: '#7c3aed' },
  { name: '青蓝', color: '#0891b2' },
  { name: '石墨黑', color: '#1f2937' },
  { name: '森林绿', color: '#15803d' },
  { name: '琥珀', color: '#d97706' },
]
