import { useEffect, useState } from 'react'
import { Layout, Menu, Typography } from 'antd'
import {
  BookOutlined,
  EditOutlined,
  MessageOutlined,
  SettingOutlined,
  ApartmentOutlined,
  ClusterOutlined,
  ExperimentOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useThemeStore } from '../store/themeStore'
import { fetchAppVersion } from '../utils/appVersion'

const { Header, Sider, Content } = Layout

const menuItems = [
  { key: '/library', icon: <BookOutlined />, label: '文献库' },
  { key: '/graph', icon: <ClusterOutlined />, label: '图谱' },
  { key: '/write', icon: <EditOutlined />, label: '写作' },
  { key: '/workflow', icon: <ApartmentOutlined />, label: '工作流' },
  { key: '/chat', icon: <MessageOutlined />, label: '对话' },
  { key: '/settings', icon: <SettingOutlined />, label: '设置' },
]

export default function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const themeColor = useThemeStore((s) => s.color)
  const [appVersion, setAppVersion] = useState('')

  const activeKey = '/' + location.pathname.split('/')[1]

  useEffect(() => {
    let cancelled = false
    fetchAppVersion().then((v) => {
      if (!cancelled) setAppVersion(v)
    })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <Layout className="app-layout">
      <Sider className="app-sider" breakpoint="lg" collapsedWidth={0} theme="light" width={220}>
        <div className="app-brand">
          <div
            className="app-brand-logo"
            style={{
              background: `linear-gradient(135deg, ${themeColor}, #2563eb)`,
              boxShadow: `0 6px 14px ${themeColor}33`,
            }}
          >
            <ExperimentOutlined />
          </div>
          <Typography.Title level={4} style={{ margin: 0, color: themeColor }}>
            科研助手
          </Typography.Title>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[activeKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
        <div
          style={{
            position: 'absolute',
            bottom: 16,
            left: 16,
            right: 16,
            fontSize: 11,
            color: '#9ca3af',
            padding: '8px 10px',
            borderTop: '1px solid var(--app-border)',
          }}
        >
          ResearchMate · v{appVersion || '加载中'}
        </div>
      </Sider>
      <Layout>
        <Header
          className="app-header"
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            alignItems: 'center',
            padding: '0 24px',
          }}
        >
          <span
            style={{
              fontSize: 12,
              color: '#2563eb',
              background: '#eff6ff',
              border: '1px solid #dbeafe',
              borderRadius: 999,
              padding: '3px 12px',
            }}
          >
            本地单用户模式
          </span>
        </Header>
        <Content className="app-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
