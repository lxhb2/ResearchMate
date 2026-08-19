import { api, streamSSE } from './client'
import type { Conversation } from '../types'
import type { AgentContext } from './agent'

export const chatApi = {
  send: async (
    message: string,
    conversationId?: string,
    useLibrary = false,
    webSearch = false,
    contexts: AgentContext[] = [],
  ): Promise<{ answer: string; conversation_id: string; conversation: Conversation }> => {
    const { data } = await api.post('/chat', {
      message,
      conversation_id: conversationId,
      use_library: useLibrary,
      web_search: webSearch,
      contexts,
    })
    return data
  },
  // 流式问答：边生成边回调 delta，返回最终 conversation_id
  sendStream: async (
    message: string,
    conversationId: string | undefined,
    useLibrary: boolean,
    webSearch: boolean,
    onDelta: (delta: string) => void,
    signal?: AbortSignal,
    contexts: AgentContext[] = [],
  ): Promise<string | undefined> => {
    let convId: string | undefined
    await streamSSE(
      '/chat/stream',
      { message, conversation_id: conversationId, use_library: useLibrary, web_search: webSearch, contexts },
      onDelta,
      (meta) => {
        if (meta?.conversation_id) convId = String(meta.conversation_id)
      },
      signal,
    )
    return convId
  },
}

export const conversationsApi = {
  list: async (): Promise<Conversation[]> => {
    const { data } = await api.get<Conversation[]>('/conversations')
    return data
  },
  get: async (id: string): Promise<Conversation> => {
    const { data } = await api.get<Conversation>(`/conversations/${id}`)
    return data
  },
  remove: async (id: string): Promise<void> => {
    await api.delete(`/conversations/${id}`)
  },
}
