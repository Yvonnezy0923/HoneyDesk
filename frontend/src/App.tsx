import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { HashRouter, Routes, Route, useLocation, useNavigate } from 'react-router-dom';
import { ConfigProvider, theme as antdTheme, Badge, Avatar, Tooltip } from 'antd';
import {
  MessageOutlined,
  FileTextOutlined,
  BarChartOutlined,
  CrownOutlined,
  HistoryOutlined,
  DatabaseOutlined,
  AppstoreOutlined,
  SettingOutlined,
  BellOutlined,
  AuditOutlined,
} from '@ant-design/icons';
import { api } from './api';
import { ThemeProvider, useThemeMode, type ResolvedTheme } from './theme';
import type { Approval } from './types';
import honeyLogo from './assets/honey-logo.png';
import ChatPage from './pages/ChatPage';
import ArtifactsPage from './pages/ArtifactsPage';
import DashboardPage from './pages/DashboardPage';
import BossDashboardPage from './pages/BossDashboardPage';
import TasksPage from './pages/TasksPage';
import KnowledgePage from './pages/KnowledgePage';
import ToolsPage from './pages/ToolsPage';
import MonitorPage from './pages/MonitorPage';
import SettingsPage from './pages/SettingsPage';
import AuditPage from './pages/AuditPage';
import CompliancePage from './pages/CompliancePage';
import ApprovalDrawer from './components/ApprovalDrawer';

export interface ApprovalsCtx {
  pending: number;
  refreshPending: () => void;
  openApproval: (id?: string) => void;
  current: Approval | null;
  loading: boolean;
  decide: (id: string, decision: string, note: string, modified?: Record<string, any>) => Promise<void>;
}

const ApprovalsContext = createContext<ApprovalsCtx>({
  pending: 0,
  refreshPending: () => {},
  openApproval: () => {},
  current: null,
  loading: false,
  decide: async () => {},
});

export const useApprovals = () => useContext(ApprovalsContext);

const groups: { label: string; items: { key: string; label: string; icon: React.ReactNode }[] }[] = [
  { label: '', items: [
    { key: '/chat', label: '调度中心', icon: <MessageOutlined /> },
    { key: '/artifacts', label: '产物中心', icon: <FileTextOutlined /> },
  ]},
  { label: '数据与知识', items: [
    { key: '/knowledge', label: '知识库管理', icon: <DatabaseOutlined /> },
    { key: '/tools', label: '工具与技能', icon: <AppstoreOutlined /> },
    { key: '/monitor', label: '监控预警', icon: <BellOutlined /> },
  ]},
  { label: '分析与审计', items: [
    { key: '/boss', label: '老板视图', icon: <CrownOutlined /> },
    { key: '/dashboard', label: '数据看板', icon: <BarChartOutlined /> },
    { key: '/tasks', label: '任务记录', icon: <HistoryOutlined /> },
    { key: '/audit', label: '操作审计', icon: <AuditOutlined /> },
    { key: '/compliance', label: '合规审计', icon: <AuditOutlined /> },
  ]},
];

// 扁平化 items 用于兼容旧查询
const items = groups.flatMap(g => g.items);

const THEME_TOKENS: Record<ResolvedTheme, any> = {
  light: {
    algorithm: antdTheme.defaultAlgorithm,
    token: {
      colorPrimary: '#17A085',
      colorInfo: '#17A085',
      colorTextLightSolid: '#FFFFFF',
      colorBgLayout: '#F2F6F3',
      colorBgContainer: '#FFFFFF',
      colorBgElevated: '#FFFFFF',
      colorText: '#3A3127',
      colorTextSecondary: '#5F5848',
      colorBorder: '#DDE6E1',
      colorBorderSecondary: '#EDF1EE',
      borderRadius: 8,
    },
  },
  dark: {
    algorithm: antdTheme.darkAlgorithm,
    token: {
      colorPrimary: '#B5873B',
      colorInfo: '#B5873B',
      colorBgLayout: '#20180F',
      colorBgContainer: '#2F2212',
      colorBgElevated: '#392B18',
      colorBgSpotlight: '#44331C',
      colorText: '#F3E7C9',
      colorTextSecondary: '#CBB98E',
      colorBorder: '#51402B',
      colorBorderSecondary: '#392C1B',
      borderRadius: 6,
    },
  },
};

function FullApp() {
  const { resolved } = useThemeMode();
  const [pending, setPending] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [current, setCurrent] = useState<Approval | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', resolved);
    document.documentElement.style.colorScheme = resolved;
  }, [resolved]);

  const refreshPending = useCallback(async () => {
    try {
      const r = await api.pendingCount();
      setPending(r.pending || 0);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refreshPending();
    const t = setInterval(refreshPending, 30000);
    return () => clearInterval(t);
  }, [refreshPending]);

  const openApproval = useCallback(
    async (id?: string) => {
      if (id) {
        try {
          const all = await api.approvals('pending');
          const list: Approval[] = all.approvals || [];
          const found = id === '__first' ? list[0] || null : list.find((a) => a.id === id) || null;
          setCurrent(found);
          if (found) setDrawerOpen(true);
          return;
        } catch {
          /* ignore */
        }
      }
      try {
        const all = await api.approvals('pending');
        const list: Approval[] = all.approvals || [];
        setCurrent(list[0] || null);
        setDrawerOpen(list.length > 0);
      } catch {
        /* ignore */
      }
    },
    []
  );

  const decide = useCallback(
    async (id: string, decision: string, note: string, modified?: Record<string, any>) => {
      setLoading(true);
      try {
        await api.decide(id, { decision, reviewer: 'user', note, modified_changes: modified });
        await refreshPending();
        openApproval();
      } finally {
        setLoading(false);
      }
    },
    [refreshPending, openApproval]
  );

  const value = useMemo(
    () => ({ pending, refreshPending, openApproval, current, loading, decide }),
    [pending, refreshPending, openApproval, current, loading, decide]
  );

  return (
    <ConfigProvider theme={THEME_TOKENS[resolved]}>
      <ApprovalsContext.Provider value={value}>
        <HashRouter>
          <Shell />
        </HashRouter>
      </ApprovalsContext.Provider>
    </ConfigProvider>
  );
}

function Shell() {
  const navigate = useNavigate();
  const location = useLocation();
  const selected = '/' + (location.pathname.split('/')[1] || 'chat');
  const selectedKey = items.some((i) => i.key === selected) ? selected : '/chat';
  const ctx = useApprovals();
  const [userName, setUserName] = useState(() => localStorage.getItem('honey_user_name') || 'Admin');
  const [editingName, setEditingName] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  const saveUserName = (name: string) => {
    const trimmed = name.trim() || 'Admin';
    setUserName(trimmed);
    localStorage.setItem('honey_user_name', trimmed);
    setEditingName(false);
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <img src={honeyLogo} alt="HoneyDesk 蜜方" className="brand-logo-img" />
          <div>
            <div className="brand-title">HoneyDesk 蜜方</div>
            <div className="brand-sub">跨境电商 Agent 工作台</div>
          </div>
        </div>
        <nav>
          {groups.map((g) => (
            <React.Fragment key={g.label || Math.random()}>
              {g.label && <div className="nav-group">{g.label}</div>}
              {g.items.map((i) => (
                <button
                  key={i.key}
                  className={`nav-item${selectedKey === i.key ? ' active' : ''}`}
                  onClick={() => navigate(i.key)}
                >
                  {i.icon}
                  <span>{i.label}</span>
                </button>
              ))}
            </React.Fragment>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="sidebar-user">
            <SettingOutlined className="sidebar-user-icon" onClick={() => navigate('/settings')} />
            {editingName ? (
              <input
                ref={nameRef}
                className="sidebar-user-input"
                defaultValue={userName}
                autoFocus
                onBlur={(e) => saveUserName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') saveUserName((e.target as HTMLInputElement).value);
                  if (e.key === 'Escape') setEditingName(false);
                }}
              />
            ) : (
              <span className="sidebar-user-name" onDoubleClick={() => setEditingName(true)}>{userName}</span>
            )}
          </div>
        </div>
      </aside>
      <div className="main-wrap">
        <header className="topbar">
          <div className="topbar-title">
            {items.find((i) => i.key === selectedKey)?.label}
            <span className="en">{selectedKey.replace('/', '')}</span>
          </div>
          <div style={{ flex: 1 }} />
          <Tooltip title={ctx.pending ? `${ctx.pending} 条待审批` : '审批待办'}>
            <Badge count={ctx.pending} size="small" offset={[-4, 2]}>
              <Avatar
                shape="square"
                icon={<BellOutlined />}
                style={{ background: 'var(--primary-soft)', color: 'var(--primary)', cursor: 'pointer' }}
                onClick={() => ctx.openApproval()}
              />
            </Badge>
          </Tooltip>
        </header>
        <div className="content">
          <Routes>
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/artifacts" element={<ArtifactsPage />} />
            <Route path="/boss" element={<BossDashboardPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/tasks" element={<TasksPage />} />
            <Route path="/knowledge" element={<KnowledgePage />} />
            <Route path="/tools" element={<ToolsPage />} />
            <Route path="/monitor" element={<MonitorPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/compliance" element={<CompliancePage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<ChatPage />} />
          </Routes>
        </div>
      </div>
      <ApprovalDrawer />
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <FullApp />
    </ThemeProvider>
  );
}