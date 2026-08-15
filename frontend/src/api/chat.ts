import { api } from './client'
import type { Conversation } from '../types'

export const chatApi = {
  send: async (
    message: string,
    conversationId?: string,
    useLibrary = false,
    webSearch = false,
  ): Promise<{ answer: string; conversation_id: string; conversation: Conversation }> => {
    const { data } = await api.post('/chat', {
      message,
      conversation_id: conversationId,
      use_library: useLibrary,
      web_search: webSearch,
    })
    return data
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
