import { useEffect, useState, useRef, useCallback } from 'react';
import {
  Card, Table, Tag, Button, Row, Col, Statistic, Space, message, Modal,
  Form, Input, Select, InputNumber, Switch, Empty, Tooltip, Alert,
  Segmented, Popconfirm, Radio, Dropdown,
} from 'antd';
import {
  ReloadOutlined, PlusOutlined, DeleteOutlined, EditOutlined,
  BellOutlined, ThunderboltOutlined, HistoryOutlined, SettingOutlined,
  ExclamationCircleFilled, CheckCircleFilled, FilterOutlined, ArrowUpOutlined, ArrowDownOutlined,
} from '@ant-design/icons';
import { api } from '../api';

type Severity = 'high' | 'medium' | 'low';
type ThresholdType = 'fixed' | 'moving_avg' | 'pct_change' | 'field_ratio';
type Comparison = 'lt' | 'lte' | 'gt' | 'gte' | 'eq';

const SEV_COLORS: Record<Severity, string> = { high: 'red', medium: 'orange', low: 'blue' };
const SEV_LABEL: Record<Severity, string> = { high: '严重', medium: '中等', low: '一般' };
const SEV_ORDER: Record<Severity, number> = { high: 0, medium: 1, low: 2 };
const SCOPE_LABEL: Record<string, string> = { operations: '运营', supply: '供应链', ads: '广告', general: '通用' };
const COMP_LABEL: Record<Comparison, string> = { lt: '<', lte: '≤', gt: '>', gte: '≥', eq: '=' };
const AGG_LABEL: Record<string, string> = { sum: '求和', avg: '均值', max: '最大值', min: '最小值', latest: '最新值' };
const TT_LABEL: Record<ThresholdType, string> = {
  fixed: '固定阈值',
  moving_avg: '滑动平均±标准差',
  pct_change: '环比变化率',
  field_ratio: '字段比值',
};
const FREQ_LABEL: Record<string, string> = {
  '1h': '每小时', '2h': '每2小时', '6h': '每6小时',
  '12h': '每12小时', '24h': '每天', '72h': '每3天',
};

interface RuleData {
  id: string;
  name: string;
  enabled: boolean;
  table: string;
  table_label: string;
  field: string;
  field_label: string;
  dimension: string;
  dimension_label: string;
  aggregation: string;
  threshold_type: ThresholdType;
  comparison: Comparison;
  threshold_value: number | null;
  reference_field: string | null;
  window: number | null;
  stddev_multiplier: number | null;
  direction: string | null;
  pct_threshold: number | null;
  severity: Severity;
  scope: string;
  message_template: string;
  created_at: string;
  updated_at: string;
  last_triggered_at: string | null;
}

interface SparklineData {
  dates: string[];
  values: number[];
  threshold: number | null;
  threshold_label: string;
  outliers: { index: number; date: string; value: number }[];
}

// ─── UTC → 东八区时间格式化 ───
function toLocalTime(utcStr: string): string {
  if (!utcStr) return '-';
  try {
    // 后端返回的是 UTC 时间但无时区标记，追加 Z 强制按 UTC 解析
    const d = new Date(utcStr.endsWith('Z') ? utcStr : utcStr + 'Z');
    return new Intl.DateTimeFormat('zh-CN', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(d).replace(/\//g, '-');
  } catch {
    return utcStr.slice(0, 16);
  }
}

// ─── SVG sparkline ───
function MiniSparkline({ data, width = 300, height = 56 }: { data: SparklineData; width?: number; height?: number }) {
  const { values, threshold, outliers, threshold_label } = data;
  const hasData = values && values.length > 0;

  if (!hasData) {
    return (
      <div style={{ width, height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted-2)', fontSize: 11 }}>
        暂无数据
      </div>
    );
  }

  const pad = { t: 6, r: 6, b: 18, l: 6 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const min = Math.min(...values) * 0.9;
  const max = Math.max(...values, threshold ?? -Infinity) * 1.1;
  const range = max - min || 1;
  const n = values.length;
  const xScale = (i: number) => pad.l + (i / Math.max(n - 1, 1)) * w;
  const yScale = (v: number) => pad.t + h - ((v - min) / range) * h;
  const outlierColor = '#ff4d4f';

  if (n === 1) {
    const cx = pad.l + w / 2;
    const cy = yScale(values[0]);
    return (
      <svg width={width} height={height} style={{ display: 'block' }}>
        <circle cx={cx} cy={cy} r="3" fill="var(--primary)" />
        <text x={pad.l} y={pad.t + h + 13} fill="var(--muted-2)" fontSize="8">{data.dates[0]?.slice(5) ?? ''}</text>
        {threshold != null && (
          <line x1={pad.l} y1={yScale(threshold)} x2={pad.l + w} y2={yScale(threshold)}
            stroke="#faad14" strokeWidth="1" strokeDasharray="4,3" />
        )}
        <text x={pad.l + w} y={pad.t + h + 13} fill="var(--muted-2)" fontSize="8" textAnchor="end">
          仅1个数据点
        </text>
      </svg>
    );
  }

  const points = values.map((v, i) => `${xScale(i)},${yScale(v)}`).join(' ');

  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      <defs>
        <linearGradient id={`sf-${data.dates[0] ?? ''}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--primary)" stopOpacity=".25" />
          <stop offset="100%" stopColor="var(--primary)" stopOpacity=".02" />
        </linearGradient>
      </defs>
      <path d={`M${points} L${xScale(n - 1)},${pad.t + h} L${xScale(0)},${pad.t + h} Z`}
        fill={`url(#sf-${data.dates[0] ?? ''})`} />
      <path d={`M${points}`} fill="none" stroke="var(--primary)" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      {threshold != null && (
        <>
          <line x1={pad.l} y1={yScale(threshold)} x2={pad.l + w} y2={yScale(threshold)}
            stroke="#faad14" strokeWidth="1" strokeDasharray="4,3" />
          <text x={pad.l + w - 2} y={yScale(threshold) - 2} fill="#faad14" fontSize="8" textAnchor="end">
            {threshold_label}
          </text>
        </>
      )}
      {outliers.map((o) => (
        <circle key={o.index} cx={xScale(o.index)} cy={yScale(o.value)} r="3.5" fill={outlierColor} stroke="#fff" strokeWidth="1" />
      ))}
      <text x={pad.l} y={pad.t + h + 13} fill="var(--muted-2)" fontSize="8">{data.dates[0]?.slice(5) ?? ''}</text>
      <text x={pad.l + w} y={pad.t + h + 13} fill="var(--muted-2)" fontSize="8" textAnchor="end">
        {data.dates[n - 1]?.slice(5) ?? ''}
      </text>
      {outliers.length > 0 && (
        <text x={pad.l + w} y={pad.t + 10} fill={outlierColor} fontSize="9" textAnchor="end" fontWeight="bold">
          {outliers.length}个异常
        </text>
      )}
    </svg>
  );
}

// ─── 历史记录（含处理按钮） ───
function AlertHistory({ ruleId }: { ruleId?: string }) {
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.monitorHistory(ruleId);
      setHistory(r.history || []);
    } finally {
      setLoading(false);
    }
  }, [ruleId]);

  useEffect(() => { load(); }, [load]);

  const handleResolve = async (alertId: string) => {
    try {
      const r = await api.updateAlertStatus(alertId, 'resolved', '已在监控预警中确认处理');
      if (r.ok ?? true) {
        message.success('已标记为已处理');
        load();
      }
    } catch {
      message.error('操作失败');
    }
  };

  return (
    <div>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={history}
        size="small"
        pagination={{ pageSize: 10, size: 'small' }}
        locale={{ emptyText: <Empty description="暂无预警历史" /> }}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 150, render: (v: string) => toLocalTime(v) },
          { title: '严重度', dataIndex: 'severity', width: 70, render: (v: string) => <Tag color={SEV_COLORS[v as Severity] ?? 'default'}>{SEV_LABEL[v as Severity] ?? v}</Tag> },
          { title: 'SKU', dataIndex: 'sku', width: 110 },
          { title: '标题', dataIndex: 'title', ellipsis: true },
          {
            title: '状态', dataIndex: 'status', width: 90,
            render: (v: string, r: any) => {
              if (v === 'resolved') return <Tag color="green">已处理</Tag>;
              if (v === 'acknowledged') return <Tag color="blue">已确认</Tag>;
              return (
                <Popconfirm
                  title="将此预警标记为已处理？"
                  onConfirm={() => handleResolve(r.id)}
                  okText="确认"
                  cancelText="取消"
                >
                  <Tag color="red" style={{ cursor: 'pointer' }}>待处理</Tag>
                </Popconfirm>
              );
            },
          },
        ]}
      />
    </div>
  );
}

// ─── 主页面 ───
export default function MonitorPage() {
  const [rules, setRules] = useState<RuleData[]>([]);
  const [loading, setLoading] = useState(true);
  const [fields, setFields] = useState<any[]>([]);
  const [sparklines, setSparklines] = useState<Record<string, SparklineData>>({});
  const [sparkLoading, setSparkLoading] = useState<Record<string, boolean>>({});
  const [modalOpen, setModalOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState('rules');
  const [form] = Form.useForm();
  const [evaluating, setEvaluating] = useState(false);
  const [selectedTable, setSelectedTable] = useState<string>('');
  const [selectedField, setSelectedField] = useState<string>('');
  const [frequency, setFrequency] = useState('1h');
  const [freqOpen, setFreqOpen] = useState(false);
  // 筛选与排序
  const [scopeFilter, setScopeFilter] = useState<string>('all');
  const [sevSort, setSevSort] = useState<'asc' | 'desc' | null>(null);
  const loadRef = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r0, r1] = await Promise.all([api.monitorRules(), api.monitorFields()]);
      setRules(r0.rules || []);
      setFields(r1.tables || []);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadFrequency = useCallback(async () => {
    try {
      const r = await api.monitorFrequency();
      if (r.frequency) setFrequency(r.frequency);
    } catch { /* ignore */ }
  }, []);

  const loadSparkline = useCallback(async (ruleId: string) => {
    setSparkLoading(prev => ({ ...prev, [ruleId]: true }));
    try {
      const r = await api.monitorRuleData(ruleId, 30);
      if (r.dates && r.values) {
        setSparklines(prev => ({ ...prev, [ruleId]: r }));
      }
    } finally {
      setSparkLoading(prev => ({ ...prev, [ruleId]: false }));
    }
  }, []);

  useEffect(() => {
    if (loadRef.current) return;
    loadRef.current = true;
    load();
    loadFrequency();
  }, [load, loadFrequency]);

  useEffect(() => {
    rules.forEach(r => { loadSparkline(r.id); });
  }, [rules, loadSparkline]);

  // 筛选 + 排序后的规则
  const filteredRules = rules.filter(r => scopeFilter === 'all' || r.scope === scopeFilter);
  const sortedRules = [...filteredRules].sort((a, b) => {
    if (sevSort === 'asc') return SEV_ORDER[a.severity] - SEV_ORDER[b.severity];
    if (sevSort === 'desc') return SEV_ORDER[b.severity] - SEV_ORDER[a.severity];
    return 0;
  });

  const enabledCount = rules.filter(r => r.enabled).length;
  const totalTriggered = rules.filter(r => r.last_triggered_at).length;

  const availableFields = fields.find(t => t.table === selectedTable)?.fields ?? [];

  const openCreate = () => {
    setEditId(null);
    form.resetFields();
    setSelectedTable('');
    setSelectedField('');
    setModalOpen(true);
  };

  const openEdit = (rule: RuleData) => {
    setEditId(rule.id);
    setSelectedTable(rule.table);
    setSelectedField(rule.field);
    form.setFieldsValue({
      name: rule.name, enabled: rule.enabled, table: rule.table, field: rule.field,
      dimension: rule.dimension, aggregation: rule.aggregation,
      threshold_type: rule.threshold_type, comparison: rule.comparison,
      threshold_value: rule.threshold_value, reference_field: rule.reference_field,
      window: rule.window, stddev_multiplier: rule.stddev_multiplier,
      direction: rule.direction, pct_threshold: rule.pct_threshold,
      severity: rule.severity, scope: rule.scope, message_template: rule.message_template,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const vals = await form.validateFields();
      setSaving(true);
      const payload = { ...vals };
      if (payload.threshold_type !== 'fixed') delete payload.threshold_value;
      if (payload.threshold_type !== 'moving_avg') { delete payload.window; delete payload.stddev_multiplier; delete payload.direction; }
      if (payload.threshold_type !== 'field_ratio') delete payload.reference_field;
      if (payload.threshold_type !== 'pct_change') delete payload.pct_threshold;
      if (editId) {
        await api.monitorUpdateRule(editId, payload);
        message.success('规则已更新');
      } else {
        await api.monitorCreateRule(payload);
        message.success('规则已创建');
      }
      setModalOpen(false);
      load();
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (ruleId: string) => {
    await api.monitorDeleteRule(ruleId);
    message.success('规则已删除');
    load();
  };

  const handleEvaluate = async () => {
    setEvaluating(true);
    try {
      const r = await api.monitorEvaluateAll();
      const triggered = (r.triggered || []).filter((t: any) => t.alert_id);
      message.success(`评估完成，触发 ${triggered.length} 条预警`);
      load();
    } finally {
      setEvaluating(false);
    }
  };

  const handleToggle = async (rule: RuleData) => {
    await api.monitorUpdateRule(rule.id, { ...rule, enabled: !rule.enabled });
    load();
  };

  const handleSetFrequency = async (freq: string) => {
    try {
      await api.monitorSetFrequency(freq);
      setFrequency(freq);
      setFreqOpen(false);
      message.success(`评估频率已设为 ${FREQ_LABEL[freq] || freq}`);
    } catch {
      message.error('设置失败');
    }
  };

  const thresholdType = Form.useWatch('threshold_type', form);

  // ─── 渲染规则卡 ───
  const renderRuleCard = (rule: RuleData) => {
    const spark = sparklines[rule.id];
    const sparkLoadingThis = sparkLoading[rule.id];
    const hasOutliers = spark && spark.outliers && spark.outliers.length > 0;

    return (
      <Card
        key={rule.id}
        size="small"
        variant="borderless"
        style={{
          marginBottom: 12,
          borderLeft: `3px solid ${rule.enabled ? 'var(--primary)' : 'var(--border)'}`,
          opacity: rule.enabled ? 1 : 0.55,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          {/* 左侧信息 */}
          <div style={{ flex: '0 0 280px', minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <b style={{ fontSize: 14 }}>{rule.name}</b>
              <Tag color={SEV_COLORS[rule.severity]} style={{ margin: 0 }}>{SEV_LABEL[rule.severity]}</Tag>
              <Tag style={{ margin: 0 }}>{SCOPE_LABEL[rule.scope] || rule.scope}</Tag>
            </div>
            <div style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.6 }}>
              <span style={{ fontFamily: 'monospace' }}>{rule.table_label}.{rule.field_label}</span>
              <span style={{ margin: '0 6px' }}>·</span>
              {TT_LABEL[rule.threshold_type]}
              {rule.threshold_type === 'fixed' && rule.threshold_value != null && (
                <span>：{COMP_LABEL[rule.comparison]} {rule.threshold_value}</span>
              )}
              {rule.threshold_type === 'moving_avg' && rule.window && (
                <span>：{rule.window}日 ±{rule.stddev_multiplier}σ</span>
              )}
              {rule.threshold_type === 'field_ratio' && rule.reference_field && (
                <span>：≥ {rule.threshold_value}</span>
              )}
              {rule.last_triggered_at && (
                <><br /><span>上次触发：{toLocalTime(rule.last_triggered_at)}</span></>
              )}
            </div>
          </div>

          {/* 中部折线图 */}
          <div style={{ flex: 1, display: 'flex', justifyContent: 'center' }}>
            {sparkLoadingThis ? (
              <div style={{ width: 300, height: 56, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted-2)', fontSize: 11 }}>
                加载中...
              </div>
            ) : spark ? (
              <MiniSparkline data={spark} width={300} height={56} />
            ) : (
              <div style={{ width: 300, height: 56, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted-2)', fontSize: 11 }}>
                暂无数据
              </div>
            )}
          </div>

          {/* 右侧操作 */}
          <div style={{ flex: '0 0 100px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
            <Tooltip title={rule.enabled ? '停用' : '启用'}>
              <Switch size="small" checked={rule.enabled} onChange={() => handleToggle(rule)} />
            </Tooltip>
            <Space size={4}>
              <Tooltip title="编辑"><Button type="text" size="small" icon={<EditOutlined />} onClick={() => openEdit(rule)} /></Tooltip>
              <Popconfirm title="确定删除此规则？" onConfirm={() => handleDelete(rule.id)}>
                <Tooltip title="删除"><Button type="text" size="small" icon={<DeleteOutlined />} danger /></Tooltip>
              </Popconfirm>
            </Space>
          </div>
        </div>
      </Card>
    );
  };

  return (
    <div>
      {/* 顶部提示 */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, background: 'var(--surface-2)', padding: '8px 12px', borderRadius: 6, color: 'var(--muted)', marginBottom: 16 }}>
        <ExclamationCircleFilled style={{ color: 'var(--muted-2)', marginTop: 2 }} />
        <div style={{ fontSize: 12 }}>
          监控预警：设置数据阈值规则，系统自动按设定的频率评估，异常时写入预警记录。
          <div style={{ marginTop: 2 }}>支持固定阈值、滑动平均、字段比值、环比变化等多种阈值方式，每个指标自动展示近30日走势图。</div>
        </div>
      </div>

      {/* 统计卡片 */}
      <Row gutter={[14, 14]} style={{ marginBottom: 16 }}>
        <Col span={6}><Card variant="borderless" size="small"><Statistic title="规则总数" value={rules.length} prefix={<SettingOutlined />} /></Card></Col>
        <Col span={6}><Card variant="borderless" size="small"><Statistic title="启用中" value={enabledCount} valueStyle={{ color: 'var(--primary)' }} prefix={<CheckCircleFilled />} /></Card></Col>
        <Col span={6}><Card variant="borderless" size="small"><Statistic title="曾触发规则" value={totalTriggered} valueStyle={{ color: '#faad14' }} prefix={<BellOutlined />} /></Card></Col>
        <Col span={6}>
          <Card variant="borderless" size="small" hoverable onClick={() => setFreqOpen(true)} style={{ cursor: 'pointer' }}>
            <Statistic title="评估频率" value={FREQ_LABEL[frequency] || frequency} prefix={<ThunderboltOutlined />} />
          </Card>
        </Col>
      </Row>

      {/* 操作栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12, alignItems: 'center' }}>
        <Segmented
          value={activeTab}
          onChange={setActiveTab}
          options={[
            { value: 'rules', label: <><SettingOutlined /> 规则列表</> },
            { value: 'history', label: <><HistoryOutlined /> 预警历史</> },
          ]}
        />
        <Space>
          {/* 筛选排序 */}
          {activeTab === 'rules' && (
            <>
              <Select
                size="small"
                value={scopeFilter}
                onChange={setScopeFilter}
                style={{ width: 100 }}
                prefix={<FilterOutlined />}
                options={[
                  { value: 'all', label: '全部域' },
                  { value: 'supply', label: '供应链' },
                  { value: 'ads', label: '广告' },
                  { value: 'operations', label: '运营' },
                  { value: 'general', label: '通用' },
                ]}
              />
              <Select
                size="small"
                value={sevSort ?? 'none'}
                onChange={(v) => setSevSort(v === 'none' ? null : v)}
                style={{ width: 110 }}
                options={[
                  { value: 'none', label: '默认排序' },
                  { value: 'asc', label: '紧急↑ 升序' },
                  { value: 'desc', label: '紧急↓ 降序' },
                ]}
              />
            </>
          )}
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          {activeTab === 'rules' && (
            <>
              <Button icon={<ThunderboltOutlined />} loading={evaluating} onClick={handleEvaluate}>立即评估</Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建规则</Button>
            </>
          )}
        </Space>
      </div>

      {/* 内容 */}
      {activeTab === 'rules' ? (
        sortedRules.length === 0 && !loading ? (
          <Empty description="暂无预警规则，点击「新建规则」创建">
            <Button type="primary" onClick={openCreate}>新建规则</Button>
          </Empty>
        ) : (
          <div style={{ maxHeight: 'calc(100vh - 340px)', overflowY: 'auto', paddingRight: 4 }}>
            {sortedRules.map(renderRuleCard)}
          </div>
        )
      ) : (
        <AlertHistory />
      )}

      {/* 频率设置弹窗 */}
      <Modal title="设置评估频率" open={freqOpen} onCancel={() => setFreqOpen(false)} footer={null} width={360}>
        <div style={{ padding: '12px 0' }}>
          <Radio.Group value={frequency} onChange={(e) => handleSetFrequency(e.target.value)}>
            <Space direction="vertical">
              <Radio value="1h">每小时（整点）</Radio>
              <Radio value="2h">每2小时</Radio>
              <Radio value="6h">每6小时</Radio>
              <Radio value="12h">每12小时</Radio>
              <Radio value="24h">每天（午夜）</Radio>
              <Radio value="72h">每3天</Radio>
            </Space>
          </Radio.Group>
          <div style={{ marginTop: 16, fontSize: 12, color: 'var(--muted)' }}>
            当前频率：<b>{FREQ_LABEL[frequency] || frequency}</b>
          </div>
        </div>
      </Modal>

      {/* ─── 新建/编辑规则弹窗 ─── */}
      <Modal
        title={editId ? '编辑规则' : '新建预警规则'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSave}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        width={640}
      >
        <Form form={form} layout="vertical" initialValues={{
          enabled: true, dimension: 'sku', aggregation: 'avg',
          threshold_type: 'fixed', comparison: 'lt', severity: 'medium', scope: 'supply',
          window: 7, stddev_multiplier: 2, direction: 'both', pct_threshold: 50,
        }}>
          <Form.Item name="name" label="规则名称" rules={[{ required: true, message: '请输入规则名称' }]}>
            <Input placeholder="例如：库存告急" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="table" label="监控表" rules={[{ required: true, message: '请选择表' }]}>
                <Select
                  placeholder="选择业务表"
                  onChange={(v: string) => { setSelectedTable(v); setSelectedField(''); form.setFieldValue('field', undefined); }}
                  options={fields.map((t: any) => ({ value: t.table, label: `${t.table_label} (${t.table})` }))}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="field" label="监控字段" rules={[{ required: true, message: '请选择字段' }]}>
                <Select
                  placeholder="选择字段"
                  disabled={!selectedTable}
                  onChange={(v: string) => {
                    setSelectedField(v);
                    const f = availableFields.find((x: any) => x.name === v);
                    if (f) form.setFieldValue('aggregation', f.suggested_agg);
                  }}
                  options={availableFields.map((f: any) => ({ value: f.name, label: `${f.label} (${f.name})` }))}
                />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="dimension" label="分组维度">
                <Select options={[{ value: 'sku', label: 'SKU' }, { value: 'campaign', label: '广告活动' }, { value: 'warehouse', label: '仓库' }]} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="aggregation" label="聚合方式">
                <Select options={Object.entries(AGG_LABEL).map(([k, v]) => ({ value: k, label: v }))} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="severity" label="严重度">
                <Select options={[
                  { value: 'high', label: '🔴 严重' },
                  { value: 'medium', label: '🟠 中等' },
                  { value: 'low', label: '🔵 一般' },
                ]} />
              </Form.Item>
            </Col>
          </Row>

          <div style={{ background: 'var(--surface-2)', padding: '12px 12px 0', borderRadius: 6, marginBottom: 12 }}>
            <Form.Item name="threshold_type" label="阈值类型">
              <Select options={[
                { value: 'fixed', label: '固定阈值' },
                { value: 'moving_avg', label: '滑动平均 ± 标准差' },
                { value: 'field_ratio', label: '字段比值' },
                { value: 'pct_change', label: '环比变化率' },
              ]} />
            </Form.Item>

            {thresholdType === 'fixed' && (
              <Row gutter={12}>
                <Col span={6}><Form.Item name="comparison" label="比较方式"><Select options={[
                  { value: 'lt', label: '<' }, { value: 'lte', label: '≤' },
                  { value: 'gt', label: '>' }, { value: 'gte', label: '≥' }, { value: 'eq', label: '=' },
                ]} /></Form.Item></Col>
                <Col span={12}><Form.Item name="threshold_value" label="阈值" rules={[{ required: true, message: '请输入阈值' }]}><InputNumber style={{ width: '100%' }} placeholder="例如：50" /></Form.Item></Col>
                <Col span={6}><Form.Item label="参照" style={{ marginTop: 22 }}><span style={{ fontSize: 12, color: 'var(--muted)' }}>直接与数值比较</span></Form.Item></Col>
              </Row>
            )}
            {thresholdType === 'moving_avg' && (
              <Row gutter={12}>
                <Col span={6}><Form.Item name="window" label="滑动窗口"><Select options={[{ value: 3, label: '3日' }, { value: 7, label: '7日' }, { value: 15, label: '15日' }, { value: 30, label: '30日' }]} /></Form.Item></Col>
                <Col span={6}><Form.Item name="stddev_multiplier" label="标准差倍数"><Select options={[{ value: 1, label: '±1σ' }, { value: 2, label: '±2σ' }, { value: 3, label: '±3σ' }]} /></Form.Item></Col>
                <Col span={6}><Form.Item name="direction" label="偏差方向"><Select options={[{ value: 'above', label: '高于均值' }, { value: 'below', label: '低于均值' }, { value: 'both', label: '双向偏离' }]} /></Form.Item></Col>
                <Col span={6}><Form.Item label="参照" style={{ marginTop: 22 }}><span style={{ fontSize: 12, color: 'var(--muted)' }}>与历史均值比较</span></Form.Item></Col>
              </Row>
            )}
            {thresholdType === 'field_ratio' && (
              <Row gutter={12}>
                <Col span={6}><Form.Item name="comparison" label="比较方式"><Select options={[{ value: 'gte', label: '≥' }, { value: 'gt', label: '>' }]} /></Form.Item></Col>
                <Col span={8}><Form.Item name="reference_field" label="参考字段"><Select placeholder="选择参考字段" disabled={!selectedTable} options={availableFields.filter((f: any) => f.name !== selectedField).map((f: any) => ({ value: f.name, label: f.label }))} /></Form.Item></Col>
                <Col span={6}><Form.Item name="threshold_value" label="比值阈值"><InputNumber style={{ width: '100%' }} min={0} max={10} step={0.1} placeholder="0.9" /></Form.Item></Col>
                <Col span={4}><Form.Item label="参照" style={{ marginTop: 22 }}><span style={{ fontSize: 12, color: 'var(--muted)' }}>字段A/字段B</span></Form.Item></Col>
              </Row>
            )}
            {thresholdType === 'pct_change' && (
              <Row gutter={12}>
                <Col span={6}><Form.Item name="comparison" label="比较方式"><Select options={[{ value: 'gt', label: '> 上升' }, { value: 'lt', label: '< 下降' }]} /></Form.Item></Col>
                <Col span={6}><Form.Item name="pct_threshold" label="变化率阈值(%)"><InputNumber style={{ width: '100%' }} min={0} max={1000} placeholder="50" /></Form.Item></Col>
                <Col span={6}><Form.Item label="参照" style={{ marginTop: 22 }}><span style={{ fontSize: 12, color: 'var(--muted)' }}>与上一日比较</span></Form.Item></Col>
              </Row>
            )}
          </div>

          <Row gutter={12}>
            <Col span={8}><Form.Item name="scope" label="作用域"><Select options={[{ value: 'supply', label: '供应链' }, { value: 'ads', label: '广告' }, { value: 'operations', label: '运营' }, { value: 'general', label: '通用' }]} /></Form.Item></Col>
            <Col span={4}><Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item></Col>
          </Row>
          <Form.Item name="message_template" label="预警消息模板" tooltip="可用变量：{sku} {value} {threshold} {mean} {std} {ratio} {field_label} {ref_label}">
            <Input.TextArea rows={2} placeholder="例如：{sku} {field_label} {value} 触发阈值 {threshold}" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}