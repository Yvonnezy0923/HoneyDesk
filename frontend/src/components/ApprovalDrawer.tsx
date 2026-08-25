import { useEffect, useState } from 'react';
import {
  Drawer,
  Descriptions,
  Tag,
  Button,
  Space,
  Input,
  Divider,
  Alert,
  Table,
  Typography,
  Segmented,
} from 'antd';
import {
  CheckOutlined,
  CloseOutlined,
  EditOutlined,
  ClockCircleOutlined,
  DatabaseOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { useApprovals } from '../App';
import { AGENTS } from '../types';

const AGENT_COLOR: Record<string, string> = {
  ops_query: '#1E3A8A',
  ops_listing: '#4338CA',
  supply_query: '#0F766E',
  ads_query: '#B45309',
};

export default function ApprovalDrawer() {
  const { current, openApproval, decide, loading } = useApprovals();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState('');
  const [mode, setMode] = useState<'approved' | 'modified' | 'rejected'>('approved');
  const [modified, setModified] = useState<Record<string, any>>({});

  useEffect(() => {
    if (current) {
      setOpen(true);
      setNote('');
      setMode('approved');
      // 初始化修改态为 after 值
      const after: Record<string, any> = {};
      const changes = current.changes?._record || current.changes || {};
      Object.entries(changes || {}).forEach(([k, v]) => {
        if (Array.isArray(v)) after[k] = v[1];
        else after[k] = v as any;
      });
      setModified(after);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current]);

  const close = () => setOpen(false);

  if (!current) {
    return (
      <Drawer
        width={620}
        title="审批待办"
        open={Boolean(open && current)}
        onClose={close}
        footer={
          <Space style={{ display: 'flex', justifyContent: 'center' }}>
            <Button onClick={close}>关闭</Button>
          </Space>
        }
      >
        <Alert
          type="info"
          showIcon
          message="暂无待审批事项"
          description="当 Agent 产生数据库写操作时会创建审批，审批项会出现在这里。"
        />
      </Drawer>
    );
  }

  const agent = AGENTS[current.agent_code] || {
    name: current.agent_code,
    scope: '',
    desc: '',
    color: AGENT_COLOR[current.agent_code] || '#475569',
  };

  const diffRows = Object.entries(current.changes || {})
    .filter(([k]) => k !== '_record') // _record 里含整条记录
    .map(([field, v]) => ({ field, before: Array.isArray(v) ? v[0] : '', after: Array.isArray(v) ? v[1] : v }));

  const recordRows = current.changes?._record
    ? Object.entries(current.changes._record as Record<string, any>).map(([k, v]) => ({
        field: k,
        value: typeof v === 'object' ? JSON.stringify(v) : String(v),
      }))
    : [];

  const statusColor: Record<string, string> = {
    pending: 'orange',
    approved: 'green',
    rejected: 'red',
    timeout: 'default',
    modified: 'blue',
  };

  const onDecide = async () => {
    const payload =
      mode === 'modified'
        ? { ...(current.changes || {}), _record: { ...(current.changes?._record || {}), ...modified } }
        : undefined;
    await decide(current.id, mode, note, payload);
    // decide 内部会刷新下一个审批；关闭当前
    setOpen(false);
  };

  return (
    <Drawer
      width={640}
      title={
        <Space>
          <DatabaseOutlined style={{ color: agent.color }} />
          <span>审批 · {current.table_name}</span>
          <Tag color={statusColor[current.status] || 'default'}>{current.status}</Tag>
        </Space>
      }
      open={open}
      onClose={close}
      footer={
        current.status === 'pending' ? (
          <Space style={{ display: 'flex', justifyContent: 'flex-end', gap: 12, flexWrap: 'wrap' }}>
            <Input
              placeholder="审批意见（可选）"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              style={{ width: 300 }}
              allowClear
            />
            <Button onClick={close}>稍后处理</Button>
            <Button danger icon={<CloseOutlined />} disabled={loading} onClick={onDecide}>
              拒绝
            </Button>
            <Button
              icon={mode === 'modified' ? <EditOutlined /> : <CheckOutlined />}
              type="primary"
              loading={loading}
              onClick={onDecide}
            >
              {mode === 'modified' ? '按修改后批准' : '批准'}
            </Button>
          </Space>
        ) : (
          <Space style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Button onClick={close}>关闭</Button>
          </Space>
        )
      }
    >
      <Descriptions column={2} size="small" bordered style={{ marginBottom: 16 }}>
        <Descriptions.Item label="Agent">
          <Tag color={agent.color}>{agent.name}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="任务">
          <Typography.Text code style={{ fontSize: 12 }}>
            {current.task_id}
          </Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="记录标识" span={2}>
          {current.record_key}
        </Descriptions.Item>
        <Descriptions.Item label="创建时间">
          {dayjs(current.created_at).format('YYYY-MM-DD HH:mm')}
        </Descriptions.Item>
        <Descriptions.Item label="超时时间">
          <Space size={4}>
            <ClockCircleOutlined />
            {dayjs(current.timeout_at).format('MM-DD HH:mm')}
          </Space>
        </Descriptions.Item>
      </Descriptions>

      <Divider orientation="left" plain>
        变更理由
      </Divider>
      <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
        {current.reason || '（无理由）'}
      </Typography.Paragraph>
      {current.evidence && (
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>
          依据：{current.evidence}
        </Typography.Paragraph>
      )}

      {diffRows.length > 0 && (
        <>
          <Divider orientation="left" plain>
            字段变更对比
          </Divider>
          <Table
            size="small"
            dataSource={diffRows}
            rowKey="field"
            pagination={false}
            columns={[
              { title: '字段', dataIndex: 'field', width: 160 },
              {
                title: '原值',
                dataIndex: 'before',
                render: (v) => <span style={{ color: '#ef4444', textDecoration: 'line-through' }}>{String(v)}</span>,
              },
              {
                title: '新值',
                dataIndex: 'after',
                render: (v, row) =>
                  mode === 'modified' ? (
                    <Input
                      value={String(modified[row.field] ?? v)}
                      onChange={(e) => setModified((m) => ({ ...m, [row.field]: e.target.value }))}
                      style={{ minWidth: 160 }}
                    />
                  ) : (
                    <span style={{ color: '#16a34a', fontWeight: 600 }}>{String(v)}</span>
                  ),
              },
            ]}
          />
        </>
      )}

      {recordRows.length > 0 && (
        <>
          <Divider orientation="left" plain>
            目标记录（整条）
          </Divider>
          <Table
            size="small"
            dataSource={recordRows}
            rowKey="field"
            pagination={false}
            columns={[
              { title: '字段', dataIndex: 'field', width: 200 },
              { title: '值', dataIndex: 'value' },
            ]}
          />
        </>
      )}

      {current.status === 'pending' && diffRows.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <Segmented
            options={[
              { label: '原样批准', value: 'approved' },
              { label: '修改后批准', value: 'modified' },
              { label: '拒绝', value: 'rejected' },
            ]}
            value={mode}
            onChange={(v) => setMode(v as any)}
            block
          />
          {mode === 'modified' && (
            <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8 }}>
              在上方「新值」列直接编辑字段值，点击批准即按修改后内容落库。
            </Typography.Paragraph>
          )}
        </div>
      )}

      {/* 编辑内容在「字段变更对比」的新值列中完成 */}
    </Drawer>
  );
}