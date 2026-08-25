import { useEffect, useState } from 'react';
import { Card, Table, Tag, Tabs, Select, Space, Empty, Button, Tooltip } from 'antd';
import { ReloadOutlined, ReadOutlined, EditOutlined, CheckCircleOutlined, ExclamationCircleFilled } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../api';
import { AGENTS } from '../types';

const LOG_TYPES: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  read: { label: '读', color: 'green', icon: <ReadOutlined /> },
  write: { label: '写', color: 'orange', icon: <EditOutlined /> },
};

const RESULT_META: Record<string, { label: string; color: string }> = {
  success: { label: '成功', color: 'green' },
  applied: { label: '已落库', color: 'green' },
  blocked: { label: '已拦截', color: 'red' },
  failed: { label: '失败', color: 'red' },
};

// 后端以 UTC（naive，无时区标识）存储，展示统一转东八区
const fmtUtc8 = (v?: string) => {
  if (!v) return '-';
  const hasTz = /[zZ]|[+-]\d\d:\d\d$/.test(v);
  return (hasTz ? dayjs(v) : dayjs(v).add(8, 'hour')).format('MM-DD HH:mm:ss');
};

export default function AuditPage() {
  const [logs, setLogs] = useState<any[]>([]);
  const [records, setRecords] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [agent, setAgent] = useState('all');

  const load = async () => {
    setLoading(true);
    try {
      const params: Record<string, any> = {};
      if (agent !== 'all') params.agent_code = agent;
      const [l, r] = await Promise.allSettled([api.logs(params), api.approvalRecords()]);
      setLogs(l.status === 'fulfilled' ? l.value.logs || [] : []);
      setRecords(r.status === 'fulfilled' ? r.value.records || [] : []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [agent]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Card variant="borderless">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
        <div style={{ flex: 1, display: 'flex', alignItems: 'flex-start', gap: 8, background: 'var(--surface-2)', padding: '7px 12px', borderRadius: 6, color: 'var(--muted)' }}>
          <ExclamationCircleFilled style={{ color: 'var(--muted-2)', marginTop: 2 }} />
          <span style={{ fontSize: 12 }}>
            提示：写操作需在对话中触发 Agent 规划后进入审批流；审批记录与操作日志只能由应用层追加，无法在管理端删除，保证可审计性。
          </span>
        </div>
        <Space>
          <Select
            value={agent}
            onChange={setAgent}
            style={{ width: 140 }}
            options={[{ value: 'all', label: '全部 Agent' }, ...Object.entries(AGENTS).map(([c, a]) => ({ value: c, label: a.name }))]}
          />
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        </Space>
      </div>
      <Tabs
        items={[
          {
            key: 'logs',
            label: `操作日志（${logs.length}）`,
            children: (
              <Table
                rowKey="audit_id"
                loading={loading}
                dataSource={logs}
                size="small"
                pagination={{ pageSize: 15, showSizeChanger: false }}
                locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
                columns={[
                  {
                    title: '类型',
                    dataIndex: 'op_type',
                    width: 70,
                    render: (v: string) => {
                      const m = LOG_TYPES[v] || { label: v, color: 'default', icon: null };
                      return <Tag color={m.color}>{m.label}</Tag>;
                    },
                  },
                  { title: '审计 ID', dataIndex: 'audit_id', width: 170, render: (v: string) => <Tag style={{ fontFamily: 'monospace' }}>{v}</Tag> },
                  { title: '动作', dataIndex: 'action', width: 150, render: (v: string) => v || '-' },
                  { title: 'Agent', dataIndex: 'agent_code', width: 110, render: (v: string) => <Tag color={AGENTS[v]?.color || '#475569'} className="agent-tag">{AGENTS[v]?.name || v || '-'}</Tag> },
                  { title: '数据表', dataIndex: 'table_name', width: 150, render: (v: string) => <span style={{ fontFamily: 'monospace' }}>{v || '-'}</span> },
                  {
                    title: '结果',
                    dataIndex: 'result',
                    width: 90,
                    render: (v: string) => <Tag color={RESULT_META[v]?.color}>{RESULT_META[v]?.label || v}</Tag>,
                  },
                  { title: '任务', dataIndex: 'task_id', width: 170, render: (v: string) => <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{v || '-'}</span> },
                  {
                    title: '时间',
                    dataIndex: 'created_at',
                    width: 150,
                    render: (v: string) => fmtUtc8(v),
                  },
                ]}
              />
            ),
          },
          {
            key: 'records',
            label: `审批记录（${records.length}）`,
            children: (
              <Table
                rowKey="id"
                dataSource={records}
                size="small"
                pagination={{ pageSize: 15, showSizeChanger: false }}
                locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
                columns={[
                  { title: '审批 ID', dataIndex: 'approval_id', width: 170, render: (v: string) => <Tag style={{ fontFamily: 'monospace' }}>{v}</Tag> },
                  { title: 'Agent', dataIndex: 'agent_code', width: 110, render: (v: string) => <Tag color={AGENTS[v]?.color || '#475569'} className="agent-tag">{AGENTS[v]?.name || v}</Tag> },
                  { title: '数据表', dataIndex: 'table_name', width: 150, render: (v: string) => <span style={{ fontFamily: 'monospace' }}>{v || '-'}</span> },
                  {
                    title: '决策',
                    dataIndex: 'decision',
                    width: 90,
                    render: (v: string) => {
                      const map: Record<string, { t: string; c: string }> = {
                        approved: { t: '批准', c: 'green' },
                        rejected: { t: '拒绝', c: 'red' },
                        modified: { t: '修改', c: 'blue' },
                        timeout: { t: '超时', c: 'default' },
                      };
                      const m = map[v] || { t: v, c: 'default' };
                      return <Tag color={m.c} icon={v === 'approved' ? <CheckCircleOutlined /> : undefined}>{m.t}</Tag>;
                    },
                  },
                  { title: '审批人', dataIndex: 'reviewer', width: 90, render: (v: string) => v || '-' },
                  { title: '意见', dataIndex: 'note', ellipsis: true, render: (v: string) => v || '-' },
                  {
                    title: '时间',
                    dataIndex: 'decided_at',
                    width: 150,
                    render: (v: string) => fmtUtc8(v),
                  },
                ]}
              />
            ),
          },
        ]}
      />
    </Card>
  );
}