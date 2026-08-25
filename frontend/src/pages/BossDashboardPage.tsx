import { useEffect, useState } from 'react';
import { Card, Row, Col, Table, Spin, Empty, Tag, Tooltip } from 'antd';
import {
  ShoppingOutlined,
  InboxOutlined,
  BarChartOutlined,
  AlertOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import { api } from '../api';

const SCOPE_META: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  operations: { label: '运营板块', color: '#5B9BD5', icon: <ShoppingOutlined /> },
  supply: { label: '供应链板块', color: '#9C7BD8', icon: <InboxOutlined /> },
  ads: { label: '广告板块', color: '#E89A62', icon: <BarChartOutlined /> },
};

const SEVERITY_LEVEL: Record<string, { text: string; color: string }> = {
  high: { text: '高', color: 'red' },
  medium: { text: '中', color: 'orange' },
  low: { text: '低', color: 'green' },
};

const STATUS_LABEL: Record<string, string> = {
  created: '已创建',
  new: '新',
  acknowledged: '已确认',
  resolved: '已解决',
  ignored: '已忽略',
};

function fmtK(v: number | undefined): string {
  if (v === undefined || v === null) return '0';
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(2) + 'M';
  if (v >= 1_000) return (v / 1_000).toFixed(1) + 'K';
  return String(v);
}

export default function BossDashboardPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const v = await api.bossView();
        setData(v);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <Spin style={{ display: 'block', margin: '80px auto' }} />;
  if (!data) return <Empty description="暂无数据" style={{ marginTop: 80 }} />;

  const { panels = {}, alerts = {}, recent_alerts = [], cost = {} } = data;
  const op = panels.operations || {};
  const sp = panels.supply || {};
  const ad = panels.ads || {};

  return (
    <div>
      <style>{OUTLINE_CSS}</style>
      <div className="boss-head">
        <div>
          <div className="boss-title">老板全局视图</div>
          <div style={{ fontSize: 12, color: 'var(--muted-2)' }}>
            三板块聚合 · 成本统计 · 全局预警（只读，无写操作入口）
          </div>
        </div>
        <Tag icon={<SafetyCertificateOutlined />} color="green">只读视图</Tag>
      </div>

      {/* ───── 三板块并排聚合 ───── */}
      <Row gutter={[14, 14]} className="dash-row">
        <Col flex="1" style={{ minWidth: 280 }}>
          <Card variant="borderless" title={<span style={{ color: SCOPE_META.operations.color }}><ShoppingOutlined /> 运营板块</span>}>
            <MetricRow items={[
              { label: '总营收 $', value: fmtK(op.revenue) },
              { label: '订单数', value: fmtK(op.orders) },
              { label: '在售商品', value: fmtK(op.products) },
            ]} />
            <div className="boss-subline">
              Listing 产出 <b>{fmtK(op.listings)}</b> ｜ 退款/退货 <b>{fmtK(op.refunds)}</b>
            </div>
          </Card>
        </Col>
        <Col flex="1" style={{ minWidth: 280 }}>
          <Card variant="borderless" title={<span style={{ color: SCOPE_META.supply.color }}><InboxOutlined /> 供应链板块</span>}>
            <MetricRow items={[
              { label: '可售库存', value: fmtK(sp.onhand) },
              { label: '在途', value: fmtK(sp.in_transit) },
              { label: '缺货风险 SKU', value: fmtK(sp.low_stock) },
            ]} />
            <div className="boss-subline">
              补货计划 <b>{fmtK(sp.replenishment_plans)}</b> 份待跟进
            </div>
          </Card>
        </Col>
        <Col flex="1" style={{ minWidth: 280 }}>
          <Card variant="borderless" title={<span style={{ color: SCOPE_META.ads.color }}><BarChartOutlined /> 广告板块</span>}>
            <MetricRow items={[
              { label: '花费 $', value: fmtK(ad.spend) },
              { label: '销售额 $', value: fmtK(ad.sales) },
              { label: 'ACOS', value: ad.acos ? (ad.acos * 100).toFixed(1) + '%' : '0%' },
            ]} />
            <div className="boss-subline">
              预算记录 <b>{fmtK(ad.budgets)}</b> 条
            </div>
          </Card>
        </Col>
      </Row>

      {/* ───── 成本雷达 + 全局预警统计 ───── */}
      <Row gutter={[14, 14]} className="dash-row" style={{ marginTop: 14, alignItems: 'stretch' }}>
        <Col flex="5" style={{ minWidth: 420 }}>
          <Card variant="borderless" title={<span>成本雷达</span>}>
            <Row gutter={[12, 12]}>
              {[
                { label: '累计估算成本 $', value: cost.total_usd?.toFixed(2) ?? '0.00', accent: true },
                { label: '今日成本 $', value: cost.today_usd?.toFixed(2) ?? '0.00' },
                { label: '累计 Token', value: fmtK(cost.tokens) },
                { label: '今日 Token', value: fmtK(cost.tokens_today) },
              ].map((it) => (
                <Col span={6} key={it.label}>
                  <div className="boss-stat">
                    <div style={{
                      fontSize: 22, fontWeight: 800,
                      color: it.accent ? '#16a34a' : 'var(--text)',
                      lineHeight: 1.1,
                    }}>{it.value}</div>
                    <div style={{ fontSize: 12, color: 'var(--muted-2)', marginTop: 4 }}>{it.label}</div>
                  </div>
                </Col>
              ))}
            </Row>
            <div className="boss-subline">
              按模型名估算的混合费率折算（美元），仅供参考，非账单级精度。
            </div>
          </Card>
        </Col>
        <Col flex="6" style={{ minWidth: 480 }}>
          <Card
            variant="borderless"
            title={<span><AlertOutlined /> 全局预警汇总</span>}
            style={{ height: '100%' }}
          >
            <Row gutter={[12, 12]}>
              {[
                { label: '预警总数', value: alerts.total ?? 0 },
                { label: '待处理', value: alerts.open ?? 0 },
                { label: '高危', value: alerts.severe ?? 0, bad: true },
              ].map((it) => (
                <Col span={8} key={it.label}>
                  <div className="boss-stat">
                    <div style={{ fontSize: 26, fontWeight: 800, color: it.bad ? '#dc2626' : 'var(--text)', lineHeight: 1.1 }}>{it.value}</div>
                    <div style={{ fontSize: 12, color: 'var(--muted-2)', marginTop: 4 }}>{it.label}</div>
                  </div>
                </Col>
              ))}
            </Row>
            {alerts.by_type && Object.keys(alerts.by_type).length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 }}>
                {Object.entries(alerts.by_type).map(([k, v]) => (
                  <Tag key={k} color="processing">{AlertLabel(k)} {v as number}</Tag>
                ))}
              </div>
            )}
          </Card>
        </Col>
      </Row>

      {/* ───── 预警列表（全宽） ───── */}
      <Row gutter={[14, 14]} className="dash-row" style={{ marginTop: 14 }}>
        <Col span={24}>
          <Card variant="borderless" title={<span><AlertOutlined /> 预警详情</span>}>
            <AlertTable rows={recent_alerts} />
          </Card>
        </Col>
      </Row>
    </div>
  );
}

const OUTLINE_CSS =
  '.dash-row > .ant-col { display: flex; }' +
  '.dash-row .ant-card { flex: 1; }' +
  '.boss-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:14px; }' +
  '.boss-title { font-size:20px; font-weight:800; color:var(--text); }' +
  '.boss-stat { background:var(--surface-2); border-radius:10px; padding:14px 16px; }' +
  '.boss-subline { margin-top:12px; font-size:12px; color:var(--muted-2); }' +
  '.metric-card { background:var(--surface-2); border-radius:10px; padding:12px 14px; flex:1; min-width:0; }' +
  '.metric-value { font-size:22px; font-weight:800; color:var(--text); line-height:1.15; }' +
  '.metric-label { font-size:12px; color:var(--muted-2); margin-top:4px; }';

function MetricRow({ items }: { items: { label: string; value: string }[] }) {
  return (
    <Row gutter={[8, 8]}>
      {items.map((it) => (
        <Col flex="1" style={{ minWidth: 80 }} key={it.label}>
          <div className="metric-card">
            <div className="metric-value">{it.value}</div>
            <div className="metric-label">{it.label}</div>
          </div>
        </Col>
      ))}
    </Row>
  );
}

function AlertLabel(k: string): string {
  return (
    {
      inventory_shortage: '库存告急',
      spend_surge: '花费激增',
      conversion_drop: '转化骤降',
      budget_depleted: '预算耗尽',
      ctr_abnormal: 'CTR 异常',
      logistics_delay: '物流延误',
      price_mutation: '价格突变',
      review_surge: '差评激增',
    }[k] ?? k
  );
}

function AlertTable({ rows }: { rows: any[] }) {
  const cols = [
    { title: '等级', dataIndex: 'severity', key: 'severity', width: 60,
      render: (v: string) => {
        const m = SEVERITY_LEVEL[v] || SEVERITY_LEVEL.medium;
        return <Tag color={m.color}>{m.text}</Tag>;
      } },
    { title: '标题', dataIndex: 'title', key: 'title',
      render: (v: string) => <Tooltip title={v}><span style={{ fontSize: 13 }}>{v}</span></Tooltip> },
    { title: 'SKU', dataIndex: 'sku', key: 'sku', width: 90, render: (v: string) => <span style={{ fontSize: 12 }}>{v || '—'}</span> },
    { title: '状态', dataIndex: 'status', key: 'status', width: 76,
      render: (v: string) => <Tag color={v === 'new' ? 'red' : v === 'resolved' ? 'green' : 'default'}>{STATUS_LABEL[v] || v}</Tag> },
  ];
  return (
    <Table
      rowKey="id"
      dataSource={rows || []}
      columns={cols as any}
      size="small"
      pagination={{ pageSize: 12, size: 'small' }}
      scroll={{ y: 300 }}
      locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无预警" /> }}
    />
  );
}

