import axios from 'axios'

export const api = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
})

// Attach JWT token to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Auto-logout on 401
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(err)
  },
)

export function setAuth(token: string) {
  localStorage.setItem('token', token)
}

export function clearAuth() {
  localStorage.removeItem('token')
  localStorage.removeItem('user')
}

export function getErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as { detail?: string } | undefined
    return data?.detail || err.message || 'Request failed'
  }
  if (err instanceof Error && err.message) {
    return err.message
  }
  return 'An unexpected error occurred'
}

// ---- SSE 流式消费 ----
// 用原生 fetch 逐块读取 SSE，把每个 data: {...} 里的 delta 累积并回调。
// onDone 会在完整流结束后调用（可带元信息，如 conversation_id）。
export async function streamSSE(
  url: string,
  body: unknown,
  onDelta: (delta: string) => void,
  onDone?: (meta?: Record<string, unknown>) => void,
  signal?: AbortSignal,
  onEvent?: (event: Record<string, unknown>) => void,
): Promise<void> {
  const token = localStorage.getItem('token')
  const res = await fetch(`/api/v1${url}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    let detail = `HTTP ${res.status}`
    try {
      const data = await res.json()
      if (data?.detail) detail = data.detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let meta: Record<string, unknown> | undefined
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      const dataLine = raw
        .split('\n')
        .map((l) => l.trim())
        .find((l) => l.startsWith('data:'))
      if (!dataLine) continue
      let obj: Record<string, unknown>
      try {
        obj = JSON.parse(dataLine.slice(5).trim())
      } catch {
        continue
      }
      if (obj.delta) onDelta(String(obj.delta))
      else if (obj.conversation_id) meta = obj
      else onEvent?.(obj)
    }
  }
  onDone?.(meta)
}
