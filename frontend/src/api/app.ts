import { api } from './client'

export interface AppInfo {
  name: string
  version: string
  repo: string
  update_url: string
}

export interface UpdateAsset {
  name: string
  url: string
  size: number | null
}

export interface UpdateCheckResult {
  ok: boolean
  error?: string
  current: string
  latest: string | null
  has_update: boolean
  release_url: string
  release_name?: string | null
  published_at?: string | null
  assets: UpdateAsset[]
}

export const appApi = {
  info: async (): Promise<AppInfo> => {
    const { data } = await api.get<AppInfo>('/app/info')
    return data
  },
  checkUpdate: async (): Promise<UpdateCheckResult> => {
    const { data } = await api.get<UpdateCheckResult>('/app/update/check')
    return data
  },
}
