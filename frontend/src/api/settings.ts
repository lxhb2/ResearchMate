import { api } from './client'

export interface AppSettings {
  llm_api_key: string
  llm_base_url: string
  llm_model: string
  embedding_model: string
  embedding_dim: number
  theme_color: string
  anysearch_enabled: boolean
  anysearch_api_key: string
  anysearch_base_url: string
  searxng_url: string
  agentsearch_url: string
  agentsearch_token: string
  agentsearch_mode: string
  academic_sources: string[]
}

export interface SettingsUpdate {
  llm_api_key?: string
  llm_base_url?: string
  llm_model?: string
  embedding_model?: string
  embedding_dim?: number
  theme_color?: string
  anysearch_enabled?: boolean
  anysearch_api_key?: string
  anysearch_base_url?: string
  searxng_url?: string
  agentsearch_url?: string
  agentsearch_token?: string
  agentsearch_mode?: string
  academic_sources?: string[]
}

export interface TestConnectionPayload {
  api_key: string
  base_url: string
  model: string
}

export interface SearchTestPayload {
  provider?: 'auto' | 'anysearch' | 'searxng' | 'agentsearch'
  anysearch_api_key?: string
  anysearch_base_url?: string
  searxng_url?: string
  agentsearch_url?: string
  agentsearch_token?: string
  agentsearch_mode?: string
}

export const settingsApi = {
  get: () => api.get<AppSettings>('/settings').then((r) => r.data),
  update: (payload: SettingsUpdate) =>
    api.put<AppSettings>('/settings', payload).then((r) => r.data),
  testConnection: (payload: TestConnectionPayload) =>
    api.post<{ ok: boolean; reply: string }>('/settings/test-connection', payload).then((r) => r.data),
  testSearch: (payload: SearchTestPayload) =>
    api.post<{ ok: boolean; engine: string; count: number }>('/settings/search/test', payload).then((r) => r.data),
  getModelPresets: () => api.get<ModelPreset[]>('/settings/model-presets').then((r) => r.data),
}

// 国内主流大模型 OpenAI 兼容接口预设
export interface ModelPreset {
  name: string
  base_url: string
  models: string[]
  embedding_model: string
  help?: string
}

// 前端兜底预设列表：当后端 /settings/model-presets 不可用时使用
// 结构需与后端 settings_service.MODEL_PRESETS 保持一致
export const MODEL_PRESETS: ModelPreset[] = [
  {
    name: '通义千问 (DashScope)',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: ['qwen-plus', 'qwen-max', 'qwen-turbo', 'qwen2.5-72b-instruct', 'qwen2.5-7b-instruct'],
    embedding_model: 'text-embedding-v3',
    help: '阿里云百炼，兼容 OpenAI 协议，model 推荐用 qwen-plus / qwen-max',
  },
  {
    name: '智谱 AI (BigModel)',
    base_url: 'https://open.bigmodel.cn/api/paas/v4',
    models: ['glm-4-plus', 'glm-4', 'glm-4-air', 'glm-4-flash', 'glm-4-flashx'],
    embedding_model: 'embedding-3',
    help: '智谱 GLM 系列，glm-4-flash 免费可用',
  },
  {
    name: 'DeepSeek',
    base_url: 'https://api.deepseek.com/v1',
    models: ['deepseek-chat', 'deepseek-reasoner', 'deepseek-coder'],
    embedding_model: '',
    help: 'DeepSeek 官方 API，价格友好，推理能力强（暂不提供 embedding）',
  },
  {
    name: 'Moonshot (Kimi)',
    base_url: 'https://api.moonshot.cn/v1',
    models: ['moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k', 'kimi-latest'],
    embedding_model: '',
    help: 'Kimi 长上下文模型，128k 适合长文献',
  },
  {
    name: '百度千帆 (兼容模式)',
    base_url: 'https://qianfan.baidubce.com/v2',
    models: ['ernie-4.0-8k-latest', 'ernie-3.5-8k', 'ernie-speed-128k', 'ernie-lite-8k'],
    embedding_model: 'embedding-v1',
    help: '百度千帆 v2 OpenAI 兼容接口',
  },
  {
    name: '讯飞星火',
    base_url: 'https://spark-api-open.xf-yun.com/v1',
    models: ['generalv3.5', 'general', 'spark-v4'],
    embedding_model: '',
    help: '讯飞星火 OpenAI 兼容接口',
  },
  {
    name: 'MiniMax',
    base_url: 'https://api.minimax.chat/v1',
    models: ['abab6.5s-chat', 'abab6.5-chat', 'abab6-chat'],
    embedding_model: '',
    help: 'MiniMax 开放平台',
  },
  {
    name: '字节豆包 (VolcEngine)',
    base_url: 'https://ark.cn-beijing.volces.com/api/v3',
    models: ['doubao-pro-32k', 'doubao-pro-128k', 'doubao-lite-32k'],
    embedding_model: '',
    help: '火山方舟，需在控制台创建接入点 ID 作为 model',
  },
  {
    name: '零一万物 (01.AI)',
    base_url: 'https://api.lingyiwanwu.com/v1',
    models: ['yi-large', 'yi-medium', 'yi-lightning', 'yi-vision'],
    embedding_model: '',
    help: '零一万物 Yi 系列',
  },
  {
    name: '阶跃星辰 (Step)',
    base_url: 'https://api.stepfun.com/v1',
    models: ['step-1-8k', 'step-1-32k', 'step-1-128k', 'step-2-16k'],
    embedding_model: '',
    help: 'Step 系列模型',
  },
  {
    name: 'OpenAI / Azure OpenAI',
    base_url: 'https://api.openai.com/v1',
    models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4.1-mini', 'o1-mini'],
    embedding_model: 'text-embedding-3-small',
    help: '官方 OpenAI 或自建代理',
  },
  {
    name: '本地 / Ollama',
    base_url: 'http://localhost:11434/v1',
    models: ['llama3.1', 'qwen2.5', 'deepseek-r1', 'phi3'],
    embedding_model: 'nomic-embed-text',
    help: '本地部署的 Ollama，无需 API Key 可填任意字符串',
  },
  {
    name: '本地 / LM Studio',
    base_url: 'http://localhost:1234/v1',
    models: ['local-model'],
    embedding_model: 'nomic-embed-text',
    help: 'LM Studio 本地服务器模式',
  },
  {
    name: 'OpenRouter',
    base_url: 'https://openrouter.ai/api/v1',
    models: ['openai/gpt-4o-mini', 'anthropic/claude-3.5-sonnet', 'google/gemini-flash-1.5'],
    embedding_model: '',
    help: 'OpenRouter 统一路由，一个 Key 访问多厂商',
  },
  {
    name: 'SiliconFlow',
    base_url: 'https://api.siliconflow.cn/v1',
    models: ['deepseek-ai/DeepSeek-V3', 'Qwen/Qwen2.5-72B-Instruct', 'meta-llama/Meta-Llama-3.1-70B-Instruct'],
    embedding_model: 'BAAI/bge-large-zh-v1.5',
    help: 'SiliconFlow 国内低价聚合平台',
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
