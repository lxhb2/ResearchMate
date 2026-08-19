import { Suspense, lazy, useEffect, useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { Spin, ConfigProvider, theme, App as AntdApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import AppLayout from './components/AppLayout'
import AgentFloat from './components/AgentFloat'
import LibraryPage from './pages/LibraryPage'
import ReaderPage from './pages/ReaderPage'
import WritePage from './pages/WritePage'
import ChatPage from './pages/ChatPage'
import SettingsPage from './pages/SettingsPage'
import WorkflowPage from './pages/WorkflowPage'
// Smart Graph 依赖 React Flow（体积较大）→ 路由级懒加载，保持首屏轻量
const SmartGraphPage = lazy(() => import('./pages/SmartGraphPage'))
import { authApi } from './api/auth'
import { useAuthStore } from './store/authStore'
import { useThemeStore } from './store/themeStore'
import { getErrorMessage } from './api/client'

export default function App() {
  const token = useAuthStore((s) => s.token)
  const setUser = useAuthStore((s) => s.setUser)
  const [booting, setBooting] = useState(!token)
  const themeColor = useThemeStore((s) => s.color)

  // Auto-login on first load: fetch a token for the default local user.
  useEffect(() => {
    if (token) return
    let cancelled = false
    authApi
      .auto()
      .then((t) => {
        if (!cancelled) setUser(t.user, t.access_token)
      })
      .catch((err) => {
        // Fall back to a visible error so it's not a blank screen.
        console.error('Auto-login failed:', getErrorMessage(err))
      })
      .finally(() => {
        if (!cancelled) setBooting(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const themeConfig = {
    algorithm: theme.defaultAlgorithm,
    token: { colorPrimary: themeColor, borderRadius: 8 },
  }

  if (booting) {
    return (
      <ConfigProvider locale={zhCN} theme={themeConfig}>
        <AntdApp>
          <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Spin tip="正在初始化科研助手…" size="large" />
          </div>
        </AntdApp>
      </ConfigProvider>
    )
  }

  return (
    <ConfigProvider locale={zhCN} theme={themeConfig}>
      <AntdApp>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={<Navigate to="/library" replace />} />
            <Route path="/library" element={<LibraryPage />} />
            <Route
              path="/graph"
              element={
                <Suspense
                  fallback={
                    <div style={{ textAlign: 'center', padding: 100 }}>
                      <Spin tip="正在加载语义图谱…" />
                    </div>
                  }
                >
                  <SmartGraphPage />
                </Suspense>
              }
            />
            <Route path="/reader/:paperId" element={<ReaderPage />} />
            <Route path="/write" element={<WritePage />} />
            <Route path="/write/:projectId" element={<WritePage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/workflow" element={<WorkflowPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/library" replace />} />
          </Route>
        </Routes>
        {/* 全局悬浮助手：所有页面可用，具备全局权限 */}
        <AgentFloat />
      </AntdApp>
    </ConfigProvider>
  )
}
