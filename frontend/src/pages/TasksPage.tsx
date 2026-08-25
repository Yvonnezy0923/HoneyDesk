import { useEffect, useState } from 'react';
import { Card, Table, Tag, Button, Drawer, Descriptions, Steps, Empty, Spin, Space, Tooltip, Select, DatePicker, Input } from 'antd';
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { api } from '../api';
import { AGENTS } from '../types';

const STATUS_META: Record<string, { color: string; label: string }> = {
  queued: { color: 'default', label: '排队中' },
  planning: { color: 'blue', label: '规划中' },
  executing: { color: 'processing', label: '执行中' },
  awaiting_approval: { color: 'orange', label: '待审批' },
  completed: { color: 'green', label: '已完成' },
  failed: { color: 'red', label: '失败' },
  terminated: { color: 'default', label: '已终止' },
};

// 工作模式（query/analysis/write/alert）含义：query=直接查数，analysis=跨表聚合+洞察分析
const MODE_META: Record<string, { color: string; label: string }> = {
  query: { color: 'blue', label: '查询' },
  analysis: { color: 'purple', label: '分析' },
  write: { color: 'orange', label: '写入' },
  alert: { color: 'magenta', label: '预警' },
};

const SCOPE_META: Record<string, string> = {
  operations: '运营',
  supply: '供应链',
  ads: '广告',
};

const FLOW = ['queued', 'planning', 'executing', 'awaiting_approval', 'completed'];

export default function TasksPage() {
  const [tasks, setTasks] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [current, setCurrent] = useState<any>(null);
  const [open, setOpen] = useState(false);
  const [agent, setAgent] = useState<string>();
  const [range, setRange] = useState<[Dayjs, Dayjs]>();
  const [query, setQuery] = useState('');

  const buildFilters = () => {
    const f: Record<string, unknown> = {};
    if (agent) f.agent_code = agent;
    if (range) {
      f.start_from = range[0].format('YYYY-MM-DD');
      f.start_to = range[1].format('YYYY-MM-DD');
    }
    const q = query.trim();
    if (q) f.keyword = q;
    return f;
  };

  const load = async (p = page, ps = pageSize) => {
    setLoading(true);
    try {
      const r = await api.tasks(p, ps, buildFilters());
      setTasks(r.tasks || []);
      setTotal(r.total || 0);
    } finally {
      setLoading(false);
    }
  };

  const resetToFirst = () => {
    setPage(1);
    load(1, pageSize);
  };

  useEffect(() => {
    load(page, pageSize);
    const t = setInterval(() => load(page, pageSize), 10000);
    return () => clearInterval(t);
  }, [page, pageSize]);

  const openDetail = async (row: any) => {
    setCurrent(row);
    setOpen(true);
    try {
      const r = await api.task(row.id);
      if (r.task) setCurrent(r.task);
    } catch {
      /* 列表行数据兜底 */
    }
  };

  const modeLabel = (v?: string) => (v ? MODE_META[v]?.label : undefined) || v || '-';
  const modeColor = (v?: string) => (v ? MODE_META[v]?.color : undefined) || 'default';

  return (
    <Card variant="borderless" bodyStyle={{ padding: '8px 16px 16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
          <Space wrap>
            <Select
              allowClear
              placeholder="按 Agent 筛选"
              value={agent}
              style={{ minWidth: 160 }}
              onChange={(v) => { setAgent(v); resetToFirst(); }}
              options={Object.keys(AGENTS).map((code) => ({
                value: code,
                label: <Space size={6}><span>{AGENTS[code].icon}</span>{AGENTS[code].name}</Space>,
              }))}
            />
            <DatePicker.RangePicker
              allowEmpty={[true, true]}
              value={range}
              onChange={(v) => { setRange(v as [Dayjs, Dayjs] | undefined); resetToFirst(); }}
            />
            <Input.Search
              allowClear
              placeholder="搜索请求内容 / 任务ID"
              value={query}
              prefix={<SearchOutlined />}
              style={{ width: 240 }}
              onChange={(e) => setQuery(e.target.value)}
              onSearch={() => resetToFirst()}
            />
          </Space>
          <Tooltip title="刷新">
            <Button size="small" type="text" icon={<ReloadOutlined />} onClick={() => load()} loading={loading} />
          </Tooltip>
        </div>
        <Table
        rowKey="id"
        loading={loading}
        dataSource={tasks}
        size="middle"
        scroll={{ x: 960 }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          pageSizeOptions: [10, 20, 50, 100],
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
        columns={[
          {
            title: '请求内容',
            dataIndex: 'user_message',
            ellipsis: true,
            render: (v: string) => <span>{v}</span>,
          },
          {
            title: 'Agent',
            dataIndex: 'agent_code',
            width: 130,
            render: (v: string) => {
              const a = AGENTS[v];
              return <Tag color={a?.color || '#475569'} className="agent-tag">{a?.name || v || '-'}</Tag>;
            },
          },
          {
            title: '模式',
            dataIndex: 'intent',
            width: 90,
            render: (v: string) => <Tag color={modeColor(v)}>{modeLabel(v)}</Tag>,
          },
          {
            title: '业务域',
            dataIndex: 'scope',
            width: 90,
            render: (v: string) => SCOPE_META[v || 'operations'] || v || '运营',
          },
          {
            title: '状态',
            dataIndex: 'status',
            width: 100,
            render: (v: string) => {
              const m = STATUS_META[v] || { color: 'default', label: v };
              return <Tag color={m.color}>{m.label}</Tag>;
            },
          },
          {
            title: '任务',
            dataIndex: 'id',
            width: 190,
            render: (v: string, r: any) => (
              <Tooltip title={v}>
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'inline-block', verticalAlign: 'middle' }}
                  onClick={() => openDetail(r)}
                >
                  {v}
                </Button>
              </Tooltip>
            ),
          },
          {
            title: '开始',
            dataIndex: 'started_at',
            width: 100,
            render: (v: string) => (v ? dayjs(v).format('MM-DD HH:mm') : '-'),
          },
        ]}
        expandedRowRender={(r) => (
          <div style={{ padding: '6px 8px' }}>
            <Descriptions size="small" column={2} style={{ marginBottom: 8 }}>
              <Descriptions.Item label="结果状态">
                {(STATUS_META[r.status] || { label: r.status }).label}
              </Descriptions.Item>
              <Descriptions.Item label="产物数">{r.artifacts?.length || 0}</Descriptions.Item>
            </Descriptions>
            {r.error ? (
              <Tag color="red">{r.error}</Tag>
            ) : (
              <pre style={{ fontSize: 12, background: 'var(--surface-2)', padding: 8, borderRadius: 6, margin: 0, whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto' }}>
                {r.answer || JSON.stringify(r.result || {}, null, 2)}
              </pre>
            )}
          </div>
        )}
        locale={{ emptyText: <Empty description="还没有任务，去调度中心发起第一条指令" /> }}
      />

      <Drawer title={`任务 #${current?.id || ''}`} width={640} open={open} onClose={() => setOpen(false)}>
        {current ? (
          <div>
            <div style={{ marginBottom: 6, fontSize: 13, color: 'var(--text)' }}>
              {current.user_message || '-'}
            </div>
            <Descriptions column={2} size="small" bordered style={{ marginBottom: 18 }}>
              <Descriptions.Item label="状态">
                <Tag color={(STATUS_META[current.status] || {}).color}>
                  {(STATUS_META[current.status] || {}).label || current.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Agent">
                <Tag color={AGENTS[current.agent_code]?.color || '#475569'} className="agent-tag">
                  {AGENTS[current.agent_code]?.name || current.agent_code || '-'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="模式">
                <Tag color={modeColor(current.intent)}>{modeLabel(current.intent)}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="业务域">
                {SCOPE_META[current.scope || 'operations'] || current.scope || '运营'}
              </Descriptions.Item>
              <Descriptions.Item label="创建">
                {current.created_at ? dayjs(current.created_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="开始">
                {current.started_at ? dayjs(current.started_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="完成">
                {current.finished_at ? dayjs(current.finished_at).format('MM-DD HH:mm:ss') : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="产物数">
                {Array.isArray(current.artifacts) ? current.artifacts.length : 0}
              </Descriptions.Item>
            </Descriptions>

            <Steps
              size="small"
              current={Math.max(0, FLOW.indexOf(current.status))}
              items={FLOW.map((s) => ({ title: (STATUS_META[s] || { label: s }).label }))}
              style={{ marginBottom: 18 }}
            />

            <b style={{ display: 'block', marginBottom: 6 }}>执行轨迹</b>
            {Array.isArray(current.trace) && current.trace.length > 0 ? (
              <Steps
                direction="vertical"
                size="small"
                current={-1}
                items={current.trace.map((t: any, i: number) => {
                  const title = typeof t === 'string' ? t : t.event || t.step || t.action || `步骤 ${i + 1}`;
                  const desc = typeof t === 'string' ? undefined : (
                    <Space size={6} wrap>
                      {t.event && <Tag color="blue">{t.event}</Tag>}
                      {t.agent && <Tag color={AGENTS[t.agent]?.color || '#475569'} className="agent-tag">{AGENTS[t.agent]?.name || t.agent}</Tag>}
                      {t.status && <Tag color="green">{t.status}</Tag>}
                      {t.time && <span style={{ fontSize: 12, color: 'var(--muted-2)' }}>{t.time}</span>}
                      {t.ts && <span style={{ fontSize: 12, color: 'var(--muted-2)' }}>{t.ts}</span>}
                    </Space>
                  );
                  return { title, description: desc };
                })}
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无轨迹" />
            )}

            {current.error && (
              <div style={{ marginTop: 12 }}>
                <Tag color="red">错误</Tag>
                <pre style={{ fontSize: 12, background: 'var(--surface-2)', padding: 8, borderRadius: 6 }}>{current.error}</pre>
              </div>
            )}
          </div>
        ) : (
          <Spin />
        )}
      </Drawer>
    </Card>
  );
}