import { appApi } from '../api/app'

const BUILD_VERSION: string = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : ''

/**
 * 获取当前应用版本：优先后端，其次 Electron 原生版本，最后使用构建时注入版本。
 * 不再使用写死的旧版本号，避免升级后界面残留旧版本。
 */
export async function fetchAppVersion(): Promise<string> {
  try {
    const info = await appApi.info()
    if (info?.version) return info.version
  } catch {
    // 后端暂不可用时继续走 Electron / 构建版本
  }
  try {
    const nativeVersion = window.researchmate ? await window.researchmate.getVersion() : ''
    if (nativeVersion) return nativeVersion
  } catch {
    // 忽略原生桥接异常
  }
  return BUILD_VERSION || '0.0.0'
}
