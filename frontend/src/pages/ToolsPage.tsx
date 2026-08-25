import { useEffect, useState } from 'react';
import { Card, Table, Tag, Button, Row, Col, Statistic, Space, Empty, message, Modal, Form, Input, Select } from 'antd';
import { ReloadOutlined, DatabaseOutlined, ExclamationCircleFilled, EditOutlined } from '@ant-design/icons';
import { api } from '../api';

const SCOPE_LABEL: Record<string, string> = {
  operations: '运营',
  supply: '供应链',
  ads: '广告',
};

const PERM_LABEL: Record<string, { text: string; color: string }> = {
  read: { text: '只读', color: 'green' },
  write: { text: '读写', color: 'orange' },
};

export default function ToolsPage() {
  const [tools, setTools] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [editOpen, setEditOpen] = useState(false);
  const [editTool, setEditTool] = useState<any>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.tools();
      setTools(sortTools(r.tools || []));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const readCount = tools.filter((t) => t.permission === 'read').length;
  const writeCount = tools.filter((t) => t.permission === 'write').length;
  const totalCalls = tools.reduce((s, t) => s + (t.call_count || 0), 0);

  const openEdit = (tool: any) => {
    setEditTool(tool);
    form.setFieldsValue({
      name: tool.name,
      description: tool.description || '',
      permission: tool.permission,
      scope: tool.scope,
      agent_codes: Array.isArray(tool.agent_codes) ? tool.agent_codes.join(', ') : '',
    });
    setEditOpen(true);
  };

  const saveEdit = async () => {
    try {
      const vals = await form.validateFields();
      setSaving(true);
      const payload: Record<string, unknown> = {
        name: vals.name,
        description: vals.description,
        permission: vals.permission,
        scope: vals.scope,
      };
      if (vals.agent_codes) {
        payload.agent_codes = vals.agent_codes.split(/[,，\s]+/).filter(Boolean);
      }
      const r = await api.updateTool(editTool.code, payload);
      if (r.ok) {
        message.success('工具已更新');
        setEditOpen(false);
        load();
      } else {
        message.error(r.message || '更新失败');
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, background: 'var(--surface-2)', padding: '8px 12px', borderRadius: 6, color: 'var(--muted)', marginBottom: 16 }}>
        <ExclamationCircleFilled style={{ color: 'var(--muted-2)', marginTop: 2 }} />
        <div style={{ fontSize: 12 }}>
          工具注册表：字段驱动自动生成
          <div style={{ marginTop: 2 }}>系统扫描已导入的业务表，根据其字段结构自动生成可被 Agent 调用的工具。读写权限的工具排在最前，可点击编辑按钮调整业务规则参数。</div>
        </div>
      </div>
      <Row gutter={[14, 14]} style={{ marginBottom: 16 }}>
        <Col span={8}><Card variant="borderless"><Statistic title="工具总数" value={tools.length} prefix={<DatabaseOutlined />} /></Card></Col>
        <Col span={8}><Card variant="borderless"><Statistic title="只读 / 读写" value={`${readCount} / ${writeCount}`} /></Card></Col>
        <Col span={8}><Card variant="borderless"><Statistic title="累计调用" value={totalCalls} /></Card></Col>
      </Row>

      <Card variant="borderless">
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        </div>
        <Table
          rowKey="code"
          loading={loading}
          dataSource={tools}
          size="middle"
          pagination={false}
          expandable={{
            expandedRowRender: (r) => (
              <div style={{ padding: '4px 8px' }}>
                <b style={{ fontSize: 12 }}>可用字段：</b>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
                  {Array.isArray(r.fields) && r.fields.length ? (
                    r.fields.map((f: any) => (
                      <Tag key={typeof f === 'string' ? f : f.name} color="blue">
                        {typeof f === 'string' ? f : `${f.name}:${f.type || '?'}`}
                      </Tag>
                    ))
                  ) : (
                    <span style={{ fontSize: 12, color: 'var(--muted-2)' }}>（自动派生）</span>
                  )}
                </div>
              </div>
            ),
          }}
          locale={{ emptyText: <Empty description="暂无工具，请先导入业务数据" /> }}
          columns={[
            { title: '工具编码', dataIndex: 'code', width: 200, render: (v: string) => <Tag>{v}</Tag> },
            { title: '名称', dataIndex: 'name' },
            { title: '数据表', dataIndex: 'table_name', width: 160, render: (v: string) => <span style={{ fontFamily: 'monospace' }}>{v}</span> },
            {
              title: '权限',
              dataIndex: 'permission',
              width: 90,
              render: (v: string) => <Tag color={PERM_LABEL[v]?.color}>{PERM_LABEL[v]?.text || v}</Tag>,
            },
            { title: '作用域', dataIndex: 'scope', width: 90, render: (v: string) => SCOPE_LABEL[v] || v || '-' },
            { title: '调用/成功', width: 120, render: (_: any, r: any) => `${r.call_count || 0} / ${r.success_count || 0}` },
            { title: '耗时(ms)', dataIndex: 'total_ms', width: 100, render: (v: number) => v || 0 },
            {
              title: '描述',
              dataIndex: 'description',
              ellipsis: true,
              render: (v: string) => <span style={{ fontSize: 12, color: 'var(--muted)' }}>{v || '-'}</span>,
            },
            {
              title: '操作',
              width: 80,
              render: (_: any, r: any) => (
                <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>
                  编辑
                </Button>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={`编辑工具 - ${editTool?.code || ''}`}
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={saveEdit}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入工具名称' }]}>
            <Input placeholder="例如：查询商品表" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} placeholder="工具的功能描述，Agent 将据此判断何时调用" />
          </Form.Item>
          <Form.Item name="permission" label="权限">
            <Select
              options={[
                { value: 'read', label: '只读' },
                { value: 'write', label: '读写（需审批）' },
              ]}
            />
          </Form.Item>
          <Form.Item name="scope" label="作用域">
            <Select
              options={[
                { value: 'operations', label: '运营' },
                { value: 'supply', label: '供应链' },
                { value: 'ads', label: '广告' },
                { value: 'general', label: '通用' },
              ]}
            />
          </Form.Item>
          <Form.Item name="agent_codes" label="可用 Agent（逗号分隔）" tooltip="哪些 Agent 可以调用此工具">
            <Input placeholder="例如：ops_query, ops_listing" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

function sortTools(tools: any[]): any[] {
  return [...tools].sort((a, b) => {
    if (a.permission === 'write' && b.permission !== 'write') return -1;
    if (a.permission !== 'write' && b.permission === 'write') return 1;
    return 0;
  });
}