import { useEffect, useMemo, useState } from 'react';
import {
  Card,
  Table,
  Tag,
  Typography,
  Modal,
  Button,
  Space,
  Select,
  Empty,
  Popconfirm,
  Tooltip,
  message,
  Switch,
  InputNumber,
  Alert,
  Spin,
} from 'antd';
import {
  FileTextOutlined,
  TableOutlined,
  FundOutlined,
  BulbOutlined,
  DeleteOutlined,
  LinkOutlined,
  ClockCircleOutlined,
  EditOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import dayjs from 'dayjs';
import { api } from '../api';
import { AGENTS } from '../types';

const DEFAULT_TTL = 15;

// 最近一次注入的目标 Agent / 会话（本地持久化，注入弹窗默认选中）
const LS_AGENT = 'hd.artifacts.inject.agent';
const LS_SESSION = 'hd.artifacts.inject.session.';
const ls = {
  get: (k: string, d = '') => {
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

const TYPE_META: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  report: { label: '报告', color: 'blue', icon: <FileTextOutlined /> },
  table: { label: '数据表', color: 'cyan', icon: <TableOutlined /> },
  strategy: { label: '策略建议', color: 'purple', icon: <FundOutlined /> },
  suggestion: { label: '建议', color: 'orange', icon: <BulbOutlined /> },
};

export default function ArtifactsPage() {
  const [list, setList] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [agent, setAgent] = useState<string>('all');
  const [viewing, setViewing] = useState<any>(null);
  const [viewOpen, setViewOpen] = useState(false);
  const [ttl, setTtl] = useState<{ open: boolean; art: any | null; days: number; is_temp: boolean }>({
    open: false,
    art: null,
    days: DEFAULT_TTL,
    is_temp: true,
  });
  const [inject, setInject] = useState<{
    open: boolean;
    art: any | null;
    agent: string;
    session: string;
    sessions: any[];
    loadingSession: boolean;
    submitting: boolean;
  }>({
    open: false,
    art: null,
    agent: '',
    session: '',
    sessions: [],
    loadingSession: false,
    submitting: false,
  });

  const load = async () => {
    setLoading(true);
    const params: Record<string, any> = {};
    if (agent !== 'all') params.agent_code = agent;
    try {
      const r = await api.artifacts(params);
      setList(r.artifacts || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [agent]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── 注入弹窗：打开时默认选中「最近一次操作的 Agent + 会话」 ──
  const openInject = async (art: any) => {
    const savedAgent = ls.get(LS_AGENT);
    const initAgent =
      savedAgent && AGENTS[savedAgent] ? savedAgent : Object.keys(AGENTS)[0] || 'ops_query';
    setInject({ open: true, art, agent: initAgent, session: '', sessions: [], loadingSession: true, submitting: false });
    await loadAgentSessions(initAgent);
  };

  const loadAgentSessions = async (code: string) => {
    setInject((p) => ({ ...p, agent: code, loadingSession: true }));
    try {
      let list = (await api.sessions(code)).sessions || [];
      if (list.length === 0) {
        const c = await api.createSession(code);
        list = [c.session];
      }
      const savedSid = ls.get(LS_SESSION + code);
      const target = (savedSid && list.find((s: any) => s.id === savedSid)) || list[0];
      setInject((p) => ({ ...p, sessions: list, session: target?.id || '', loadingSession: false }));
    } catch {
      setInject((p) => ({ ...p, loadingSession: false }));
    }
  };

  const doInject = async () => {
    const { art, agent: ag, session } = inject;
    if (!art || !ag || !session) {
      message.warning('请选择注入目标 Agent 和会话');
      return;
    }
    setInject((p) => ({ ...p, submitting: true }));
    try {
      const res = await api.injectArtifact({ artifact_id: art.id, agent_code: ag, session_id: session, task_id: '' });
      if (res.ok !== false) {
        ls.set(LS_AGENT, ag);
        ls.set(LS_SESSION + ag, session);
        message.success(`已注入「${art.title}」到 ${AGENTS[ag]?.name || ag} 会话`);
      } else {
        message.warning(res.message || '注入失败');
      }
      setInject((p) => ({ ...p, open: false }));
    } catch (e: any) {
      message.error(`注入失败：${e?.message || '网络错误'}`);
    } finally {
      setInject((p) => ({ ...p, submitting: false }));
    }
  };

  const cols = useMemo(
    () => [
      {
        title: '产物来源',
        dataIndex: 'source',
        width: 260,
        ellipsis: { showTitle: false },
        render: (v: string) =>
          v ? (
            <Tooltip title={v}>
              <Typography.Text style={{ fontSize: 12 }}>{v}</Typography.Text>
            </Tooltip>
          ) : (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>—</Typography.Text>
          ),
      },
      {
        title: '标题',
        dataIndex: 'title',
        render: (v: string, r: any) => (
          <a onClick={() => { setViewing(r); setViewOpen(true); }}>{v}</a>
        ),
      },
      {
        title: '类型',
        dataIndex: 'art_type',
        width: 110,
        render: (v: string) => {
          const meta = TYPE_META[v] || TYPE_META.report;
          return <Tag icon={meta.icon} color={meta.color}>{meta.label}</Tag>;
        },
      },
      {
        title: 'Agent',
        dataIndex: 'agent_code',
        width: 130,
        render: (v: string) => {
          const a = AGENTS[v];
          return <Tag color={a?.color || '#475569'} className="agent-tag">{a?.name || v}</Tag>;
        },
      },
      {
        title: '创建时间',
        dataIndex: 'created_at',
        width: 150,
        render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
      },
      {
        title: '有效期',
        width: 170,
        render: (_: any, r: any) =>
          r.is_temp ? (
            <Tag icon={<ClockCircleOutlined />} color={r.expired ? 'red' : 'orange'}>
              {r.expired ? '已过期' : `至 ${r.expires_at || '-'}`}
            </Tag>
          ) : (
            <Tag color="green">永久</Tag>
          ),
      },
      {
        title: '操作',
        width: 130,
        render: (_: any, r: any) => (
          <Space>
            <Tooltip title="查看">
              <Button size="small" type="text" icon={<FileTextOutlined />} onClick={() => { setViewing(r); setViewOpen(true); }} />
            </Tooltip>
            <Tooltip title="注入到对话">
              <Button size="small" type="text" icon={<LinkOutlined />} onClick={() => openInject(r)} />
            </Tooltip>
            <Tooltip title="设置有效期">
              <Button
                size="small"
                type="text"
                icon={<EditOutlined />}
                onClick={() => setTtl({ open: true, art: r, days: r.ttl_days || DEFAULT_TTL, is_temp: r.is_temp })}
              />
            </Tooltip>
            <Popconfirm
              title="删除该产物？"
              onConfirm={async () => {
                await api.deleteArtifact(r.id);
                message.success('已删除');
                load();
              }}
            >
              <Button size="small" type="text" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [load]
  );

  const doSetTtl = async () => {
    if (!ttl.art) return;
    await api.setTtl(ttl.art.id, ttl.days || DEFAULT_TTL, ttl.is_temp);
    setTtl({ open: false, art: null, days: DEFAULT_TTL, is_temp: true });
    message.success('有效期已更新');
    load();
  };

  return (
    <div>
      <Card variant="borderless">
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap', marginBottom: 12 }}>
          <div style={{ flex: 1, fontSize: 12, color: 'var(--muted-2)', minWidth: 260 }}>
            临时产物默认保留 <b>15 天</b>；被引用、注入对话后有效期顺延 15 天。可在操作列手动设置有效期时长或转为正式产物。
          </div>
          <Select
            value={agent}
            onChange={setAgent}
            style={{ width: 150 }}
            options={[{ value: 'all', label: '全部 Agent' }, ...Object.entries(AGENTS).map(([c, a]) => ({ value: c, label: a.name }))]}
          />
        </div>
        <Table
          rowKey="id"
          loading={loading}
          dataSource={list}
          columns={cols}
          size="middle"
          pagination={{ pageSize: 12, showSizeChanger: false }}
          locale={{ emptyText: <Empty description="暂无产物，去调度中心触发一次分析吧" /> }}
        />
      </Card>

      <Modal
        title={viewing?.title}
        open={viewOpen}
        onCancel={() => setViewOpen(false)}
        footer={null}
        width={720}
      >
        {viewing && (
          <div>
            <Space wrap style={{ marginBottom: 12 }}>
              {(TYPE_META[viewing.art_type] || TYPE_META.report).label && (
                <Tag color={(TYPE_META[viewing.art_type] || TYPE_META.report).color}>{(TYPE_META[viewing.art_type] || TYPE_META.report).label}</Tag>
              )}
              {AGENTS[viewing.agent_code] && <Tag color={AGENTS[viewing.agent_code].color} className="agent-tag">{AGENTS[viewing.agent_code].name}</Tag>}
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {dayjs(viewing.created_at).format('YYYY-MM-DD HH:mm')}
              </Typography.Text>
            </Space>
            {viewing.content ? (
              <div className="markdown-preview">
                <ReactMarkdown>{viewing.content}</ReactMarkdown>
              </div>
            ) : viewing.data ? (
              <pre style={{ background: '#0f172a', color: '#e2e8f0', padding: 16, borderRadius: 8, overflow: 'auto', fontSize: 12 }}>
                {JSON.stringify(viewing.data, null, 2)}
              </pre>
            ) : (
              <Empty description="该产物无正文内容" />
            )}
            {Array.isArray(viewing.sources) && viewing.sources.length > 0 && (
              <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 12 }}>
                数据溯源：{viewing.sources.map((s: any) => (typeof s === 'string' ? s : JSON.stringify(s))).join(' | ')}
              </Typography.Paragraph>
            )}
          </div>
        )}
      </Modal>

      {/* 注入到对话：手动选择目标 Agent 与会话，默认选中最近一次操作 */}
      <Modal
        title="注入到对话上下文"
        open={inject.open}
        onOk={doInject}
        okText="确认注入"
        confirmLoading={inject.submitting}
        onCancel={() => setInject((p) => ({ ...p, open: false }))}
        width={480}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="注入将把该产物作为上下文写入所选 Agent 的指定会话，可在调度中心该会话中继续基于它分析。"
        />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <div style={{ marginBottom: 6, fontSize: 12, color: 'var(--muted)' }}>目标 Agent</div>
            <Select
              value={inject.agent}
              style={{ width: '100%' }}
              loading={inject.loadingSession}
              onChange={(v) => loadAgentSessions(v)}
              options={Object.entries(AGENTS).map(([c, a]) => ({ value: c, label: `${a.icon} ${a.name}` }))}
            />
          </div>
          <div>
            <div style={{ marginBottom: 6, fontSize: 12, color: 'var(--muted)' }}>目标会话</div>
            {inject.loadingSession ? (
              <div style={{ padding: 8 }}><Spin size="small" /></div>
            ) : (
              <Select
                value={inject.session}
                style={{ width: '100%' }}
                onChange={(v) => setInject((p) => ({ ...p, session: v }))}
                options={inject.sessions.map((s: any) => ({ value: s.id, label: `${s.title || '新会话'}（${dayjs(s.last_message_at).format('MM-DD HH:mm')}）` }))}
                placeholder="选择会话（无会话将自动创建）"
              />
            )}
          </div>
          <div style={{ fontSize: 12, color: 'var(--muted-2)' }}>
            提示：默认选中最近一次注入的 Agent 与会话；切换后本地会记住你的选择。
          </div>
        </div>
      </Modal>

      {/* 设置产物有效期 */}
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
            <span style={{ fontSize: 12, color: 'var(--muted-2)' }}>关闭后转为正式产物，永久保留</span>
          </div>
        </div>
      </Modal>
    </div>
  );
}