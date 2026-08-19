export {}

declare global {
  interface Window {
    researchmate?: {
      versions: { electron: string; chrome: string }
      getVersion: () => Promise<string>
      checkForUpdates: () => Promise<{
        ok: boolean
        current: string
        available: string | null
        releaseName?: string | null
        releaseDate?: string | null
        error?: string
      }>
      downloadUpdate: () => Promise<{ ok: boolean; error?: string }>
      installUpdate: () => Promise<{ ok: boolean; error?: string }>
    }
  }
}
