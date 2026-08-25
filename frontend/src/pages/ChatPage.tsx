import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Input,
  Button,
  Space,
  Tag,
  Card,
  Empty,
  Spin,
  Alert,
  Typography,
  Tooltip,
  Modal,
  Switch,
  InputNumber,
  Popconfirm,
  Select,
} from 'antd';
import {
  SendOutlined,
  RobotOutlined,
  UserOutlined,
  BulbOutlined,
  SafetyCertificateOutlined,
  PlusOutlined,
  DeleteOutlined,
  LinkOutlined,
  ClockCircleOutlined,
  EditOutlined,
  LeftOutlined,
  RightOutlined,
  MenuFoldOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import dayjs from 'dayjs';
import { api } from '../api';
import { AGENTS } from '../types';
import type { ChatMessage, ChatSession, Artifact, Approval } from '../types';
import { useApprovals } from '../App';
import QueryResultCard from '../components/QueryResultCard';
import ErrorBoundary from '../components/ErrorBoundary';

const SUGGESTIONS = [
  '对比最近 30 天各 SKU 的销量与库存，列出需要补货的商品',
  '分析近 14 天广告投放的 ROI，给出降本增效建议',
  '查看 2025-09 至今累计销售额与订单量，按周拆分趋势',
  '汇总当前各仓库库存低于安全线的 SKU，并给出补货优先级',
];

const STATUS_DESC: Record<string, string> = {
  queued: '已排队',
  planning: '规划中',
  executing: '执行中',
  awaiting_approval: '待审批',
  completed: '已完成',
  failed: '失败',
  terminated: '已终止',
};
const STATUS_COLOR: Record<string, string> = {
  queued: 'default',
  planning: 'blue',
  executing: 'processing',
  awaiting_approval: 'orange',
  completed: 'green',
  failed: 'red',
  terminated: 'default',
};

const DEFAULT_TTL = 15;

// 调度中心历史位置持久化：切换模块后回到本页仍保留之前的 agent/会话/宽度/折叠状态
const LS_AGENT = 'hd.dispatch.agent';
const LS_SESSW = 'hd.dispatch.sessW';
const LS_STATW = 'hd.dispatch.statW';
const LS_COLLAPSE = 'hd.dispatch.collapse';
const LS_SESSION_PREFIX = 'hd.dispatch.session.';
const ls = {
  get: (k: string, d: string) => {
    try {
      return localStorage.getItem(k) ?? d;
    } catch {
      return d;
    }
  },
  set: (k: string, v: string) => {
    try {
      localStorage.setItem(k, v);
    } catch {
      /* ignore */
    }
  },
};

export default function ChatPage() {
  const [agentCode, setAgentCode] = useState(
    () => (AGENTS[ls.get(LS_AGENT, 'ops_query')] ? ls.get(LS_AGENT, 'ops_query') : 'ops_query')
  );
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionId, setSessionId] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [rename, setRename] = useState<{ open: boolean; id: string; title: string }>({
    open: false,
    id: '',
    title: '',
  });
  const [ttl, setTtl] = useState<{ open: boolean; art: Artifact | null; days: number; is_temp: boolean }>({
    open: false,
    art: null,
    days: DEFAULT_TTL,
    is_temp: true,
  });
  const listRef = useRef<HTMLDivElement>(null);
  const chatPageRef = useRef<HTMLDivElement>(null);
  const { openApproval } = useApprovals();

  const agent = AGENTS[agentCode];

  // ── 侧栏可拖拽调宽 & 可折叠（历史状态持久化） ──
  const [sessW, setSessW] = useState(() => Number(ls.get(LS_SESSW, '216')) || 216);
  const [statW, setStatW] = useState(() => Number(ls.get(LS_STATW, '316')) || 316);
  const [sessCollapsed, setSessCollapsed] = useState(() => ls.get(LS_COLLAPSE, '').includes('s'));
  const [statCollapsed, setStatCollapsed] = useState(() => ls.get(LS_COLLAPSE, '').includes('r'));
  const dragRef = useRef<'sess' | 'stat' | null>(null);

  useEffect(() => ls.set(LS_AGENT, agentCode), [agentCode]);
  useEffect(() => ls.set(LS_SESSW, String(sessW)), [sessW]);
  useEffect(() => ls.set(LS_STATW, String(statW)), [statW]);
  useEffect(
    () => ls.set(LS_COLLAPSE, `${sessCollapsed ? 's' : ''}${statCollapsed ? 'r' : ''}`),
    [sessCollapsed, statCollapsed]
  );
  useEffect(() => {
    if (sessionId) ls.set(LS_SESSION_PREFIX + agentCode, sessionId);
  }, [sessionId, agentCode]);

  const startResize =
    (which: 'sess' | 'stat') =>
    (e: React.MouseEvent) => {
      if (dragRef.current) return;
      e.preventDefault();
      dragRef.current = which;
      document.body.style.userSelect = 'none';
      document.body.style.cursor = 'col-resize';
      const rect = chatPageRef.current?.getBoundingClientRect();
      const onMove = (ev: MouseEvent) => {
        if (!rect) return;
        if (which === 'sess') {
          const w = Math.min(Math.max(ev.clientX - rect.left, 132), 400);
          setSessW(w);
        } else {
          const w = Math.min(Math.max(rect.right - ev.clientX, 232), 500);
          setStatW(w);
        }
      };
      const onUp = () => {
        dragRef.current = null;
        document.body.style.userSelect = '';
        document.body.style.cursor = '';
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    };

  // ── 会话加载（随 Agent 切换） ──
  const loadSessions = useCallback(
    async (code: string, selectId?: string) => {
      try {
        const r = await api.sessions(code);
        let list: ChatSession[] = r.sessions || [];
        if (list.length === 0) {
          const c = await api.createSession(code);
          list = [c.session];
        }
        setSessions(list);
        const stored = ls.get(LS_SESSION_PREFIX + code, '');
        const target =
          (selectId && list.find((s) => s.id === selectId)) ||
          list.find((s) => s.id === stored) ||
          list[0];
        setSessionId(target.id);
      } catch {
        /* ignore */
      }
    },
    []
  );

  // ── 右侧边栏：待审批（按 Agent）+ 临时产物（只按当前会话绑定） ──
  const refreshApprovals = useCallback(async (code: string) => {
    try {
      const r = await api.approvals('pending', code);
      setApprovals(r.approvals || []);
    } catch {
      /* ignore */
    }
  }, []);
  const refreshTemp = useCallback(async (sid: string) => {
    if (!sid) {
      setArtifacts([]);
      return;
    }
    try {
      const r = await api.artifacts({ session_id: sid, is_temp: true });
      setArtifacts(r.artifacts || []);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    loadSessions(agentCode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentCode]);
  useEffect(() => {
    refreshApprovals(agentCode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentCode, refreshApprovals]);
  useEffect(() => {
    refreshTemp(sessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, refreshTemp]);

  useEffect(() => {
    const t = setInterval(() => {
      refreshApprovals(agentCode);
      if (sessionId) refreshTemp(sessionId);
    }, 10000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentCode, sessionId, refreshApprovals, refreshTemp]);

  // ── 消息加载（随会话切换） ──
  const loadMessages = useCallback(async (sid: string) => {
    setLoading(true);
    try {
      const r = await api.messages({ session_id: sid });
      setMessages(r.messages || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (sessionId) loadMessages(sessionId);
  }, [sessionId, loadMessages]);

  useEffect(() => {
    if (!sessionId) return;
    // 双 rAF：等消息/图表渲染稳定后再瞬间定位到底部。
    // 用平滑动画容易在内容尚未渲染完时启动，最终停在顶部或半路，切换 Agent/模块回归时体验很差。
    const raf = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const el = listRef.current;
        if (el) el.scrollTo({ top: el.scrollHeight });
      });
    });
    return () => cancelAnimationFrame(raf);
  }, [sessionId, messages, loading]);

  // ── 发送 ──
  const send = useCallback(
    async (text?: string) => {
      const content = (text ?? input).trim();
      if (!content || sending) return;
      setInput('');
      setSending(true);
      await ensureSession();
      const optimistic: ChatMessage = {
        id: Date.now(),
        role: 'user',
        agent_code: agentCode,
        session_id: sessionId,
        content,
        task_id: '',
        created_at: dayjs().format('YYYY-MM-DD HH:mm:ss'),
      };
      setMessages((m) => [...m, optimistic]);
      try {
        const r = await api.sendMessage(content, agentCode, sessionId);
        if (r.assistant) setMessages((m) => [...m, { ...r.assistant, session_id: sessionId }]);
        else
          setMessages((m) => [
            ...m,
            {
              id: Date.now() + 1,
              role: 'assistant',
              agent_code: agentCode,
              session_id: sessionId,
              content: r.task?.answer || '任务已结束。',
              task_id: r.task?.task_id || '',
              created_at: dayjs().format('YYYY-MM-DD HH:mm:ss'),
            },
          ]);
        loadSessions(agentCode, sessionId);
        if (sessionId) refreshTemp(sessionId);
      } catch (e: any) {
        setMessages((m) => [
          ...m,
          {
            id: Date.now() + 1,
            role: 'assistant',
            agent_code: agentCode,
            session_id: sessionId,
            content: `⚠️ 请求失败：${e?.response?.data?.detail || e?.message || '网络错误'}`,
            task_id: '',
            created_at: dayjs().format('YYYY-MM-DD HH:mm:ss'),
          },
        ]);
      } finally {
        setSending(false);
      }
    },
    [agentCode, sessionId, input, sending]
  );

  const ensureSession = async () => {
    if (sessionId) return;
    try {
      const r = await api.createSession(agentCode);
      setSessions((list) => [r.session, ...list]);
      setSessionId(r.session.id);
    } catch {
      /* ignore */
    }
  };

  // 追问 chips 触发新一轮对话
  useEffect(() => {
    const handler = (e: Event) => {
      const text = (e as CustomEvent).detail;
      if (typeof text === 'string' && text) send(text);
    };
    window.addEventListener('honeydesk:ask', handler);
    return () => window.removeEventListener('honeydesk:ask', handler);
  }, [send]);

  const newSession = async () => {
    const r = await api.createSession(agentCode);
    loadSessions(agentCode, r.session.id);
  };

  const delSession = async (id: string) => {
    await api.deleteSession(id);
    setSessions((list) => list.filter((s) => s.id !== id));
    if (sessionId === id) {
      const rest = sessions.filter((s) => s.id !== id);
      if (rest.length > 0) setSessionId(rest[0].id);
      else setMessages([]);
    }
  };

  const doRename = async () => {
    if (!rename.id) return;
    const r = await api.renameSession(rename.id, rename.title);
    if (r.ok !== false) {
      setSessions((list) => list.map((s) => (s.id === rename.id ? { ...s, ...r } : s)));
    }
    setRename({ open: false, id: '', title: '' });
  };

  const injectArtifact = async (art: Artifact) => {
    await api.injectArtifact({
      artifact_id: art.id,
      agent_code: agentCode,
      session_id: sessionId,
    });
    if (sessionId) loadMessages(sessionId);
    if (sessionId) refreshTemp(sessionId);
  };

  const doSetTtl = async () => {
    if (!ttl.art) return;
    await api.setTtl(ttl.art.id, ttl.days || DEFAULT_TTL, ttl.is_temp);
    setTtl({ open: false, art: null, days: DEFAULT_TTL, is_temp: true });
    if (sessionId) refreshTemp(sessionId);
  };

  return (
    <div className="chat-page" ref={chatPageRef}>
      <aside
        className={`sess-pane ${sessCollapsed ? 'collapsed' : ''}`}
        style={{ width: sessCollapsed ? 0 : sessW }}
      >
        <div className="sess-head">
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>会话</span>
          <Space size={2}>
            <Tooltip title="新建会话">
              <Button size="small" type="text" icon={<PlusOutlined />} onClick={newSession} />
            </Tooltip>
            <Tooltip title="折叠会话栏">
              <Button size="small" type="text" icon={<LeftOutlined />} onClick={() => setSessCollapsed(true)} />
            </Tooltip>
          </Space>
        </div>
        <div className="sess-list">
          {sessions.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无会话" style={{ marginTop: 16 }} />
          ) : (
            sessions.map((s) => (
              <div
                key={s.id}
                className={`sess-item ${s.id === sessionId ? 'active' : ''}`}
                onClick={() => setSessionId(s.id)}
              >
                <div className="t">
                  {s.title || '新会话'}
                  <span className="sess-ops">
                    <EditOutlined
                      className="sess-op"
                      title="重命名"
                      onClick={(e) => {
                        e.stopPropagation();
                        setRename({ open: true, id: s.id, title: s.title });
                      }}
                    />
                    <DeleteOutlined
                      className="sess-op"
                      title="删除"
                      onClick={(e) => {
                        e.stopPropagation();
                        Modal.confirm({
                          title: '删除会话',
                          content: '将同时删除该会话下的所有消息，确认删除？',
                          okText: '删除',
                          okButtonProps: { danger: true },
                          onOk: () => delSession(s.id),
                        });
                      }}
                    />
                  </span>
                </div>
                <div className="sub">{s.last_message_at}</div>
              </div>
            ))
          )}
        </div>
      </aside>

      {!sessCollapsed && <div className="resizer" onMouseDown={startResize('sess')} />}

      {/* 中：对话主区 */}
      <div className="chat-pane">
        <div ref={listRef} className="msg-list">
          {loading ? (
            <div style={{ textAlign: 'center', marginTop: 40 }}>
              <Spin />
            </div>
          ) : messages.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                <span>
                  我是蜜方工作台调度中心 · {agent.name}
                  <br />
                  用一句话告诉我你想查什么、算什么，或要我写什么
                </span>
              }
              style={{ marginTop: 40 }}
            />
          ) : (
            messages.map((m) =>
              m.role === 'user' ? (
                <div className="msg user" key={m.id}>
                  <div className="msg-av" style={{ background: '#17A085' }}>
                    <UserOutlined />
                  </div>
                  <div className="msg-bubble">{m.content}</div>
                </div>
              ) : (
                <ErrorBoundary key={`eb-${m.id}`} label="该条结果渲染失败，已跳过展示。">
                  <div className="msg assistant">
                    <div className="msg-av" style={{ background: agent.color }}>
                    <RobotOutlined />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="msg-bubble markdown">
                      {m.task_id && (
                        <div style={{ marginBottom: 8, fontSize: 11, color: 'var(--muted-2)' }}>
                          <Tooltip title={m.task_id}>
                            <span>
                              任务 #{m.task_id}{' '}
                              {(m.data as any)?.status && (
                                <Tag color={STATUS_COLOR[(m.data as any).status] || 'default'}>
                                  {STATUS_DESC[(m.data as any).status] || (m.data as any).status}
                                </Tag>
                              )}
                            </span>
                          </Tooltip>
                        </div>
                      )}
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                      {(m.data as any)?.analyses?.length > 0 && (
                        <QueryResultCard data={(m.data as any) || {}} />
                      )}
                      {(m.data as any)?.approvals?.length > 0 && (
                        <Alert
                          type="warning"
                          showIcon
                          icon={<SafetyCertificateOutlined />}
                          style={{ marginTop: 10 }}
                          message={
                            <Space wrap>
                              <span>该任务包含 {(m.data as any).approvals.length} 个待审批的写操作</span>
                              <Button
                                size="small"
                                type="primary"
                                icon={<SafetyCertificateOutlined />}
                                onClick={() => openApproval('__first')}
                              >
                                去审批
                              </Button>
                            </Space>
                          }
                        />
                      )}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--muted-2)', marginTop: 4 }}>
                      {AGENTS[m.agent_code]?.name || m.agent_code} ·{' '}
                      {m.created_at ? dayjs(m.created_at).format('MM-DD HH:mm') : ''}
                    </div>
                  </div>
                  </div>
                </ErrorBoundary>
              )
            )
          )}
        </div>

        {messages.length === 0 && (
          <div className="agent-switch">
            <BulbOutlined style={{ color: '#f59e0b', marginRight: 4 }} />
            <span style={{ fontSize: 12, color: 'var(--muted)', marginRight: 6 }}>试试：</span>
            {SUGGESTIONS.slice(0, 3).map((s) => (
              <button key={s} className="sugg" onClick={() => send(s)} title={s}>
                {s.length > 30 ? s.slice(0, 30) + '…' : s}
              </button>
            ))}
          </div>
        )}

        <div className="chat-input">
          <Input.TextArea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={`向 ${agent.name} 下达指令，回车发送（Shift+Enter 换行）…`}
            autoSize={{ minRows: 1, maxRows: 4 }}
            onPressEnter={(e) => {
              if (!e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={() => send()}
            loading={sending}
            style={{ alignSelf: 'flex-end', height: 40 }}
          >
            发送
          </Button>
        </div>
      </div>

      {!statCollapsed && <div className="resizer" onMouseDown={startResize('stat')} />}

      {/* 右：与当前 Agent 绑定（Agent 下拉切换，可折叠 / 可拖拽调宽） */}
      <aside
        className={`stat-panel ${statCollapsed ? 'collapsed' : ''}`}
        style={{ width: statCollapsed ? 0 : statW }}
      >
        <div className="stat-agent-bar">
          <Select
            value={agentCode}
            style={{ flex: 1, minWidth: 0 }}
            onChange={(v) => setAgentCode(v)}
            options={Object.entries(AGENTS).map(([code, it]) => ({
              value: code,
              label: `${it.icon} ${it.name}`,
            }))}
          />
          <Tooltip title="折叠侧栏">
            <Button size="small" type="text" icon={<RightOutlined />} onClick={() => setStatCollapsed(true)} />
          </Tooltip>
        </div>

        <Card size="small" title={`待审批任务 · ${agent.name}`} variant="borderless">
          {approvals.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无待审批任务" />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {approvals.map((a) => (
                <div key={a.id} className="appr-item">
                  <div style={{ fontSize: 12, fontWeight: 600 }}>
                    {a.table_name} · {a.record_key}
                  </div>
                  <div className="side-note" style={{ margin: '3px 0 6px' }}>
                    {a.reason || a.evidence}
                  </div>
                  <Button
                    size="small"
                    type="primary"
                    ghost
                    icon={<SafetyCertificateOutlined />}
                    onClick={() => openApproval(a.id)}
                  >
                    去审批
                  </Button>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card size="small" title={`当前 Agent 能做什么 · ${agent.name}`} variant="borderless">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {agent.caps.map((c, i) => (
              <div key={c} style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                <Tag color="blue" style={{ margin: 0, flexShrink: 0 }}>
                  能力{i + 1}
                </Tag>
                <span style={{ fontSize: 12, color: 'var(--text)', lineHeight: 1.6 }}>{c}</span>
              </div>
            ))}
          </div>
          <div className="side-note" style={{ marginTop: 10 }}>
            各 Agent 会话相互隔离，跨场景引用历史产物时，请在产物中心选择产物手动「注入」为上下文。
          </div>
        </Card>

        <Card size="small" title="临时产物" variant="borderless">
          <div className="side-note">
            本期临时产物默认保留 <b>15 天</b>；被引用、注入对话后有效期顺延 15 天，也可在下方手动设置时长或转正式。
          </div>
          {artifacts.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无临时产物" style={{ marginTop: 8 }} />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
              {artifacts.slice(0, 6).map((a) => (
                <div key={a.id} className="temp-item">
                  <div style={{ fontSize: 12, fontWeight: 600 }}>{a.title}</div>
                  <div className="side-note" style={{ margin: '3px 0 6px' }}>
                    <ClockCircleOutlined /> 有效期至 {a.expires_at || '永久'}
                  </div>
                  <Space size={6}>
                    <Button
                      size="small"
                      type="primary"
                      icon={<LinkOutlined />}
                      onClick={() => injectArtifact(a)}
                    >
                      注入
                    </Button>
                    <Button
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() =>
                        setTtl({ open: true, art: a, days: a.ttl_days || DEFAULT_TTL, is_temp: a.is_temp })
                      }
                    >
                      有效期
                    </Button>
                    <Popconfirm title="删除该产物？" onConfirm={async () => { await api.deleteArtifact(a.id); if (sessionId) refreshTemp(sessionId); }}>
                      <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </Space>
                </div>
              ))}
            </div>
          )}
        </Card>
      </aside>

      {/* 重命名会话 */}
      <Modal
        title="重命名会话"
        open={rename.open}
        onOk={doRename}
        onCancel={() => setRename({ open: false, id: '', title: '' })}
        destroyOnClose
      >
        <Input
          value={rename.title}
          onChange={(e) => setRename((r) => ({ ...r, title: e.target.value }))}
          placeholder="请输入会话名称"
        />
      </Modal>

      {/* 设置有效期 */}
      <Modal
        title="设置产物有效期"
        open={ttl.open}
        onOk={doSetTtl}
        onCancel={() => setTtl({ open: false, art: null, days: DEFAULT_TTL, is_temp: true })}
        destroyOnClose
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ width: 84 }}>保留时长(天)</span>
            <InputNumber min={1} max={365} value={ttl.days} onChange={(v) => setTtl((t) => ({ ...t, days: v || DEFAULT_TTL }))} />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ width: 84 }}>临时产物</span>
            <Switch
              checked={ttl.is_temp}
              onChange={(v) => setTtl((t) => ({ ...t, is_temp: v }))}
            />
            <span className="side-note">关闭后转为正式产物，永久保留</span>
          </div>
        </div>
      </Modal>

      {sessCollapsed && (
        <button className="edge-expand left" title="展开会话栏" onClick={() => setSessCollapsed(false)}>
          <MenuFoldOutlined />
        </button>
      )}
      {statCollapsed && (
        <button className="edge-expand right" title="展开侧栏" onClick={() => setStatCollapsed(false)}>
          <MenuFoldOutlined />
        </button>
      )}
    </div>
  );
}