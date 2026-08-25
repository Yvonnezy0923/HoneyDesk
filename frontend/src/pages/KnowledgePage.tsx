import { useEffect, useState } from 'react';
import {
  Card,
  Table,
  Tag,
  Button,
  Input,
  Modal,
  Form,
  Select,
  Popconfirm,
  Statistic,
  Row,
  Col,
  Space,
  message,
  Empty,
  Tooltip,
} from 'antd';
import { PlusOutlined, DeleteOutlined, DatabaseOutlined, FileTextOutlined, SyncOutlined, ExclamationCircleFilled } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../api';

const TABLE_META: Record<string, { label: string; fields: string[] }> = {
  products: { label: '商品表', fields: ['id', 'name', 'category', 'brand', 'price', 'cost', 'status'] },
  product_materials: { label: '产品资料表', fields: ['sku', 'name', 'features', 'selling_points', 'keywords', 'target_market'] },
  listings: { label: 'Listing 表', fields: ['sku', 'market', 'title', 'search_terms'] },
  sales_orders: { label: '销售订单表', fields: ['id', 'sku', 'order_date', 'quantity', 'revenue', 'channel'] },
  competitors: { label: '竞品快照表', fields: ['sku', 'competitor_name', 'price', 'snapshot_date'] },
  inventory: { label: '库存表', fields: ['sku', 'available', 'in_transit', 'safety_stock', 'warehouse'] },
  ad_performance: { label: '广告数据表', fields: ['sku', 'campaign', 'stat_date', 'spend', 'sales', 'clicks', 'orders'] },
  ad_budgets: { label: '广告预算表', fields: ['sku', 'period', 'bid', 'daily_budget'] },
  stores: { label: '店铺表', fields: ['id', 'name'] },
};

// 'new'|'changed' → 浅橙需手动索引；'ok' → 浅绿已索引；'empty' → 灰（无数据）
const SOURCE_STYLE: Record<string, { bg: string; border: string; fg: string; tip: string }> = {
  new: { bg: '#FFF7ED', border: '#FDBA74', fg: '#C2410C', tip: '新增表，点击索引' },
  changed: { bg: '#FFF7ED', border: '#FDBA74', fg: '#B45309', tip: '数据有新增/变更，点击重新索引' },
  ok: { bg: '#F0FDF4', border: '#86EFAC', fg: '#15803D', tip: '已索引，可直接使用（点击可重索引）' },
  empty: { bg: '#F8FAFC', border: '#E2E8F0', fg: '#94A3B8', tip: '无数据' },
};

const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: 'default', label: '待处理' },
  indexing: { color: 'processing', label: '索引中' },
  ready: { color: 'green', label: '就绪' },
  failed: { color: 'red', label: '失败' },
};

export default function KnowledgePage() {
  const [docs, setDocs] = useState<any[]>([]);
  const [stats, setStats] = useState<any>({});
  const [sources, setSources] = useState<any[]>([]);
  const [syncing, setSyncing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [form] = Form.useForm();

  const load = async () => {
    setLoading(true);
    try {
      const [d, s, src] = await Promise.all([api.documents(), api.kbStats(), api.kbSync()]);
      setDocs(d.documents || []);
      setStats(s || {});
      setSources(src.sources || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const syncSources = async () => {
    setSyncing(true);
    try {
      const r = await api.kbSync();
      setSources(r.sources || []);
      message.success('数据源已同步');
    } catch (e: any) {
      message.error(`同步失败：${e?.message || '请确认已导入业务数据'}`);
    } finally {
      setSyncing(false);
    }
  };

  const ingestTable = async (table: string) => {
    message.loading({ content: `正在索引 ${TABLE_META[table]?.label}…`, key: table, duration: 0 });
    try {
      await api.ingestTable(table);
      message.success({ content: `${TABLE_META[table]?.label} 索引完成`, key: table });
      load();
    } catch (e: any) {
      message.error({ content: `索引失败：${e?.message || '请确认已导入该表数据'}`, key: table });
    }
  };

  return (
    <div>
      <Row gutter={[14, 14]} style={{ marginBottom: 16 }}>
        <Col span={8}><Card variant="borderless"><Statistic title={<span style={{ color: 'var(--text)', fontWeight: 600 }}>文档总数</span>} value={stats.docs || 0} valueStyle={{ color: 'var(--text)' }} /></Card></Col>
        <Col span={8}><Card variant="borderless"><Statistic title={<span style={{ color: 'var(--text)', fontWeight: 600 }}>就绪文档</span>} value={stats.ready || 0} valueStyle={{ color: '#15803d' }} /></Card></Col>
        <Col span={8}><Card variant="borderless"><Statistic title={<span style={{ color: 'var(--text)', fontWeight: 600 }}>向量分块数</span>} value={stats.chunks || 0} valueStyle={{ color: 'var(--text)' }} /></Card></Col>
      </Row>

      <Card variant="borderless">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
          <div style={{ flex: 1, display: 'flex', alignItems: 'flex-start', gap: 8, background: 'var(--surface-2)', padding: '7px 12px', borderRadius: 6, color: 'var(--muted)' }}>
            <ExclamationCircleFilled style={{ color: 'var(--muted-2)', marginTop: 2 }} />
            <span style={{ fontSize: 12 }}>从已导入的业务表建立语义索引，Agent 才能基于真实数据跨字段检索</span>
          </div>
          <div style={{ flex: 1 }} />
          <Space>
            <Button icon={<SyncOutlined />} onClick={load}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>
              接入文档
            </Button>
          </Space>
        </div>

        <Table
          rowKey="id"
          loading={loading}
          dataSource={docs}
          pagination={false}
          size="small"
          locale={{ emptyText: <Empty description="还没有任何知识库文档" /> }}
          columns={[
            {
              title: '标题',
              dataIndex: 'title',
              render: (v: string, r: any) => (
                <Space>
                  {r.doc_type === 'table' ? <DatabaseOutlined style={{ color: '#4338CA' }} /> : <FileTextOutlined style={{ color: '#1E3A8A' }} />}
                  <span>{v}</span>
                </Space>
              ),
            },
            { title: '类型', dataIndex: 'doc_type', width: 90, render: (v: string) => (v === 'table' ? <Tag color="purple">业务表</Tag> : <Tag>文档</Tag>) },
            { title: '作用域', dataIndex: 'scope', width: 110, render: (v: string) => v || '-' },
            { title: '分块数', dataIndex: 'chunk_count', width: 90 },
            {
              title: '状态',
              dataIndex: 'status',
              width: 100,
              render: (v: string) => {
                const m = STATUS_META[v] || { color: 'default', label: v };
                return <Tag color={m.color}>{m.label}</Tag>;
              },
            },
            { title: '创建', dataIndex: 'created_at', width: 140, render: (v: string) => dayjs(v).format('MM-DD HH:mm') },
            {
              title: '操作',
              width: 120,
              render: (_: any, r: any) =>
                r.doc_type === 'table' ? (
                  <Button size="small" onClick={() => ingestTable(r.title.replace('业务表-', ''))}>
                    重新索引
                  </Button>
                ) : (
                  <Popconfirm title="删除该文档？" onConfirm={async () => { await api.deleteDoc(r.id); message.success('已删除'); load(); }}>
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                ),
            },
          ]}
        />
      </Card>

      <Card title="业务表" variant="borderless" style={{ marginTop: 16 }}
        extra={
          <Button size="small" icon={<DatabaseOutlined />} loading={syncing} onClick={syncSources}>
            同步数据源
          </Button>
        }>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          {sources.map((s) => {
            const meta = TABLE_META[s.table];
            const st = SOURCE_STYLE[s.state] || SOURCE_STYLE.empty;
            return (
              <Tooltip key={s.table} title={st.tip}>
                <Button
                  size="small"
                  style={{ background: st.bg, borderColor: st.border, color: st.fg }}
                  icon={<DatabaseOutlined />}
                  onClick={() => ingestTable(s.table)}
                >
                  {meta?.label || s.table}（{s.rows}）
                </Button>
              </Tooltip>
            );
          })}
        </div>
        <div style={{ marginTop: 12, fontSize: 12, color: 'var(--muted-2)' }}>
          浅橙色 = 新增或数据有变更，需点击手动索引；浅绿色 = 已索引，可直接用于对话检索。
        </div>
      </Card>

      <Modal title="接入一段文档到知识库" open={addOpen} onCancel={() => setAddOpen(false)}
        onOk={async () => {
          const v = await form.validateFields();
          await api.ingestDoc(v);
          message.success('已接入并向量化');
          form.resetFields();
          setAddOpen(false);
          load();
        }}>
        <Form form={form} layout="vertical" initialValues={{ scope: 'general', source: '' }}>
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder="例如：美妆爆品运营 SOP" />
          </Form.Item>
          <Form.Item name="scope" label="作用域">
            <Select
              options={[
                { value: 'general', label: '通用' },
                { value: 'operations', label: '运营' },
                { value: 'supply', label: '供应链' },
                { value: 'ads', label: '广告' },
              ]}
            />
          </Form.Item>
          <Form.Item name="content" label="内容" rules={[{ required: true, message: '请输入内容' }]}>
            <Input.TextArea rows={6} placeholder="粘贴需要 Agent 检索引用的运营知识 / SOP / 规则…" />
          </Form.Item>
          <Form.Item name="source" label="来源">
            <Input placeholder="可选，如文件名/链接" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}