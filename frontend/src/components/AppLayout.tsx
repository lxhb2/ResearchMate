import { Layout, Menu, Typography } from 'antd'
import {
  BookOutlined,
  EditOutlined,
  MessageOutlined,
  SettingOutlined,
  ApartmentOutlined,
  ClusterOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useThemeStore } from '../store/themeStore'

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

  const activeKey = '/' + location.pathname.split('/')[1]

  return (
    <Layout className="app-layout">
      <Sider breakpoint="lg" collapsedWidth={0} theme="light" width={220}>
        <div style={{ padding: '20px 16px' }}>
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
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff',
            display: 'flex',
            justifyContent: 'flex-end',
            alignItems: 'center',
            padding: '0 24px',
          }}
        >
          <Typography.Text type="secondary">本地单用户模式</Typography.Text>
        </Header>
        <Content className="app-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
