import { api, setAuth } from './client'
import type { Token } from '../types'

export const authApi = {
  auto: async (): Promise<Token> => {
    const { data } = await api.post<Token>('/auth/auto', {})
    setAuth(data.access_token)
    return data
  },
  register: async (username: string, password: string): Promise<Token> => {
    const { data } = await api.post<Token>('/auth/register', { username, password })
    setAuth(data.access_token)
    return data
  },
  login: async (username: string, password: string): Promise<Token> => {
    const { data } = await api.post<Token>('/auth/login', { username, password })
    setAuth(data.access_token)
    return data
  },
}
