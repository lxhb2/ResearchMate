import { api, streamSSE } from './client'

export interface ModuleInfo {
  key: string
  name: string
  path: string
  icon: string
  desc: string
}

export interface Recommendation {
  matched: boolean
  module: ModuleInfo | null
  reason: string
  steps: string[]
}

export interface MemoryFile {
  name: string
  title: string
  size: number
  updated_at: string
  excerpt: string
}

export interface AgentChatResult {
  path: string
  route_label: string
  answer: string
  artifact_path?: string | null
  recommendation?: Recommendation
  tool_trace?: { tool: string; args: Record<string, unknown>; result: string }[]
}

export interface SkillInfo {
  name: string
  category: string
  description: string
  trigger_keyword?: string[]
  enabled?: boolean
}

export interface McpServer {
  name: string
  type: 'http' | 'stdio'
  url?: string
  command?: string
  args?: string[]
  enabled?: boolean
  tools?: { name: string; description?: string }[]
  description?: string
}

export interface ContextItem {
  type: 'skill' | 'tool' | 'memory' | 'module'
  name: string
  label: string
  description: string
  triggers?: string[]
}

export interface GithubRepo {
  full_name: string
  html_url: string
  description: string
  stars: number
  language: string | null
  updated_at: string
}

export interface PluginInfo {
  name: string
  valid: boolean
  version?: string
  display_name?: string
  description?: string
  author?: string
  enabled?: boolean
  active?: boolean
  skills?: string[]
  tools?: string[]
  mcp_servers?: string[]
  error?: string | null
}

// @ 引用上下文对象
export interface AgentContext {
  type: 'skill' | 'tool' | 'memory' | 'module'
  name: string
}

export const agentApi = {
  modules: () => api.get<{ modules: ModuleInfo[] }>('/agent/modules').then((r) => r.data.modules),

  recommend: (text: string) =>
    api.post<Recommendation>('/agent/recommend', { text }).then((r) => r.data),

  chat: async (
    message: string,
    useLibrary = false,
    webSearch = false,
    contexts: AgentContext[] = [],
  ): Promise<AgentChatResult> => {
    const { data } = await api.post<AgentChatResult>('/agent/chat', {
      message,
      use_library: useLibrary,
      web_search: webSearch,
      contexts,
    })
    return data
  },

  // 流式全局 Agent 对话：先收到 recommendation 事件，再 tool_trace，然后 delta 文本
  chatStream: async (
    message: string,
    useLibrary: boolean,
    webSearch: boolean,
    onRecommendation: (rec: Recommendation) => void,
    onToolTrace: (trace: { tool: string }[]) => void,
    onDelta: (delta: string) => void,
    signal?: AbortSignal,
    contexts: AgentContext[] = [],
  ): Promise<void> => {
    await streamSSE(
      '/agent/chat/stream',
      { message, use_library: useLibrary, web_search: webSearch, contexts },
      onDelta,
      undefined,
      signal,
      (evt) => {
        if (evt.recommendation) onRecommendation(evt.recommendation as Recommendation)
        else if (evt.tool_trace) onToolTrace(evt.tool_trace as { tool: string }[])
      },
    )
  },

  // 长期记忆
  memoryList: () => api.get<{ files: MemoryFile[] }>('/agent/memory').then((r) => r.data.files),
  memoryGet: (name: string) =>
    api.get<{ name: string; content: string }>(`/agent/memory/${name}`).then((r) => r.data),
  memoryWrite: (name: string, content: string, append = true) =>
    api.post(`/agent/memory/${name}`, { content, append }).then((r) => r.data),

  // Skill
  skillsList: () => api.get<{ count: number; skills: SkillInfo[] }>('/agent/skills').then((r) => r.data),
  skillRegister: (payload: Record<string, unknown>) =>
    api.post('/agent/skills', payload).then((r) => r.data),
  skillRemove: (name: string) => api.delete(`/agent/skills/${name}`).then((r) => r.data),

  // MCP
  mcpList: () => api.get<{ servers: McpServer[] }>('/agent/mcp').then((r) => r.data.servers),
  mcpSave: (payload: McpServer) => api.post('/agent/mcp', payload).then((r) => r.data),
  mcpRemove: (name: string) => api.delete(`/agent/mcp/${name}`).then((r) => r.data),
  mcpTest: (name: string) => api.post(`/agent/mcp/test/${name}`).then((r) => r.data),

  // @ 引用上下文
  contexts: () => api.get<{ count: number; items: ContextItem[] }>('/agent/contexts').then((r) => r.data.items),

  // Skill 上传（SKILL.md / 代码文件 / zip / tar.gz）
  skillUpload: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post('/agent/skills/upload', fd).then((r) => r.data)
  },

  // GitHub 搜索 & 导入
  githubSearch: (q: string) =>
    api.get<{ items: GithubRepo[] }>('/agent/skills/github/search', { params: { q } }).then((r) => r.data.items),
  githubImport: (repoUrl: string) =>
    api.post('/agent/skills/github/import', { repo_url: repoUrl }).then((r) => r.data),

  // MCP 配置上传
  mcpUpload: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post('/agent/mcp/upload', fd).then((r) => r.data)
  },

  // 插件生态
  pluginsList: () =>
    api.get<{ plugins: PluginInfo[] }>('/agent/plugins').then((r) => r.data.plugins),
  pluginInstall: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post('/agent/plugins/install', fd).then((r) => r.data)
  },
  pluginEnable: (name: string) =>
    api.post(`/agent/plugins/${name}/enable`).then((r) => r.data),
  pluginDisable: (name: string) =>
    api.post(`/agent/plugins/${name}/disable`).then((r) => r.data),
  pluginUninstall: (name: string) =>
    api.delete(`/agent/plugins/${name}`).then((r) => r.data),
}
