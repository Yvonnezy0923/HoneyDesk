import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Card,
  Row,
  Col,
  Table,
  Spin,
  Empty,
  Select,
  Progress,
  Tooltip,
} from 'antd';
import {
  CheckSquareOutlined,
  DatabaseOutlined,
  GoldOutlined,
  FireOutlined,
  RiseOutlined,
  SearchOutlined,
  BookOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import * as echarts from 'echarts';
import type { EChartsOption } from 'echarts';
import { api } from '../api';
import { useThemeMode } from '../theme';

const SCOPE_OPTIONS = [
  { value: 'all', label: '全部业务域' },
  { value: 'operations', label: '运营' },
  { value: 'ads', label: '广告' },
  { value: 'supply', label: '供应链' },
];
const DAY_OPTIONS = [
  { value: 7, label: '近 7 天' },
  { value: 14, label: '近 14 天' },
  { value: 30, label: '近 30 天' },
  { value: 90, label: '近 90 天' },
];

const OUTLINE_CSS =
  '.stat-row { display: flex; gap: 14px; }' +
  '.stat-row .stat-card { flex: 1; min-width: 0; }' +
  '.dash-row > .ant-col { display: flex; }' +
  '.dash-row .ant-card { flex: 1; }';

function fmtTokens(v: number): string {
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M';
  if (v >= 1_000) return (v / 1_000).toFixed(1) + 'K';
  return String(v || 0);
}

export default function DashboardPage() {
  const [ov, setOv] = useState<any>(null);
  const [byAction, setByAction] = useState<any[]>([]);
  const [trend, setTrend] = useState<any[]>([]);
  const [kb, setKb] = useState<any>({ docs: 0, chunks: 0 });
  const [days, setDays] = useState(14);
  const [scope, setScope] = useState('all');
  const [loading, setLoading] = useState(true);

  const loadBase = async () => {
    try {
      const [o, a, k] = await Promise.all([api.overview(), api.opByAction(), api.kbStats()]);
      setOv(o);
      setByAction(a.items || []);
      setKb(k);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadBase();
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const t = await api.trend(days, scope);
        setTrend(t.items || []);
      } catch {
        /* ignore */
      }
    })();
  }, [days, scope]);

  if (loading) return <Spin style={{ display: 'block', margin: '80px auto' }} />;
  if (!ov) return <Empty description="暂无数据，请先导入测试数据并触发任务" style={{ marginTop: 80 }} />;

  return (
    <div>
      <style>{OUTLINE_CSS}</style>

      {/* ── 总览：任务 + 工具 + 知识库 + Token 6 指标方正一排 ── */}
      <div className="stat-row">
        <Card variant="borderless" className="stat-card">
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>
            <CheckSquareOutlined style={{ marginRight: 4 }} />任务总数
          </div>
          <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--text)', lineHeight: 1 }}>{ov.tasks_total}</div>
          <div style={{ fontSize: 12, color: 'var(--muted-2)', marginTop: 8 }}>近 7 天新增 {ov.tasks_week} 个</div>
        </Card>
        <Card variant="borderless" className="stat-card">
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>
            <RiseOutlined style={{ marginRight: 4 }} />任务完成次数
          </div>
          <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--text)', lineHeight: 1 }}>{ov.tasks_completed}</div>
          <div style={{ fontSize: 12, color: 'var(--muted-2)', marginTop: 8 }}>完成率 {ov.task_completion_rate}%</div>
        </Card>
        <Card variant="borderless" className="stat-card">
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>
            <FireOutlined style={{ marginRight: 4 }} />工具调用次数
          </div>
          <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--text)', lineHeight: 1 }}>{ov.tool_calls_total}</div>
          <div style={{ fontSize: 12, color: 'var(--muted-2)', marginTop: 8 }}>累计工具操作</div>
        </Card>
        <Card variant="borderless" className="stat-card">
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>
            <GoldOutlined style={{ marginRight: 4 }} />工具调用成功率
          </div>
          <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--text)', lineHeight: 1 }}>{ov.tool_success_rate}%</div>
          <div style={{ fontSize: 12, color: 'var(--muted-2)', marginTop: 8 }}>成功 / 总调用</div>
        </Card>
        <Card variant="borderless" className="stat-card">
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>
            <SearchOutlined style={{ marginRight: 4 }} />知识库检索次数
          </div>
          <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--text)', lineHeight: 1 }}>{ov.kb_retrieval}</div>
          <div style={{ fontSize: 12, color: 'var(--muted-2)', marginTop: 8 }}>检索成功率 {ov.kb_success_rate}%</div>
        </Card>
        <Card variant="borderless" className="stat-card">
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>
            <ThunderboltOutlined style={{ marginRight: 4 }} />Token 消耗
          </div>
          <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--text)', lineHeight: 1 }}>{fmtTokens(ov.llm_tokens_today ?? ov.llm_tokens)}</div>
          <div style={{ fontSize: 12, color: 'var(--muted-2)', marginTop: 8 }}>今日消耗 · 累计 {fmtTokens(ov.llm_tokens)}</div>
        </Card>
      </div>

      {/* ── 成本雷达 + 幻觉雷达（P1 看板扩展） ── */}
      <div className="stat-row" style={{ marginTop: 14 }}>
        <Card variant="borderless" className="stat-card">
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>
            成本雷达 · LLM 估算成本
          </div>
          <div style={{ fontSize: 28, fontWeight: 800, color: '#16a34a', lineHeight: 1 }}>
            ${Number(ov.llm_cost_usd ?? 0).toFixed(2)}
          </div>
          <div style={{ fontSize: 12, color: 'var(--muted-2)', marginTop: 8 }}>
            今日 ${Number(ov.llm_cost_usd_today ?? 0).toFixed(2)} · 按模型估算，非账单精度
          </div>
        </Card>
        <Card variant="borderless" className="stat-card">
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>
            幻觉雷达 · 疑似无源断言
          </div>
          <div style={{
            fontSize: 28, fontWeight: 800,
            color: ov.hallucination_risks ? '#dc2626' : 'var(--text)',
            lineHeight: 1,
          }}>{ov.hallucination_risks ?? 0}</div>
          <div style={{ fontSize: 12, color: 'var(--muted-2)', marginTop: 8 }}>
            产出结论却无源数据支撑的次数，详情见老板视图
          </div>
        </Card>
      </div>

      {/* ── 趋势图 + 列表：左右两栏等高方正 ── */}
      <Row gutter={[14, 14]} className="dash-row" style={{ alignItems: 'stretch', marginTop: 14 }}>
        <Col span={14}>
          <Card
            title="任务 / 执行次数趋势"
            variant="borderless"
            extra={
              <div style={{ display: 'flex', gap: 8 }}>
                <Select size="small" value={scope} onChange={setScope} options={SCOPE_OPTIONS} style={{ width: 120 }} />
                <Select size="small" value={days} onChange={setDays} options={DAY_OPTIONS} style={{ width: 100 }} />
              </div>
            }
            style={{ height: '100%' }}
            bodyStyle={{ paddingBottom: 0 }}
          >
            <div style={{ fontSize: 12, color: 'var(--muted-2)', marginBottom: 2 }}>
              任务数=当日新增任务总数 ｜ 执行次数=当日工具调用次数（含成功/失败）
            </div>
            <TrendChart data={trend} />
          </Card>
        </Col>
        <Col span={10}>
          <Card
            title="工具调用与知识库"
            variant="borderless"
            style={{ height: '100%' }}
            bodyStyle={{ display: 'flex', flexDirection: 'column', gap: 16 }}
          >
            <ToolCallTable items={byAction} />
            <KbPanel kb={kb} retrieval={ov.kb_retrieval} />
          </Card>
        </Col>
      </Row>
    </div>
  );
}

function TrendChart({ data }: { data: any[] }) {
  const wrapper = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts | null>(null);
  const { resolved } = useThemeMode();
  const dark = resolved === 'dark';

  useEffect(() => {
    const el = wrapper.current;
    if (!el) return;
    const c = echarts.init(el);
    inst.current = c;
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      c.dispose();
      inst.current = null;
    };
  }, []);

  const option = useMemo<EChartsOption>(() => {
    const cats = data.map((d) => d.date);
    const tasks = data.map((d) => d.tasks ?? 0);
    const ops = data.map((d) => d.ops ?? 0);
    return {
      tooltip: { trigger: 'axis' },
      legend: {
        data: ['当日新任务', '工具执行次数'],
        top: 0,
        textStyle: { color: dark ? '#CBB98E' : '#475569' },
      },
      grid: { left: 12, right: 24, top: 32, bottom: 8, containLabel: true },
      xAxis: {
        type: 'category',
        data: cats,
        axisLabel: { color: dark ? '#B39F73' : '#64748b' },
        axisLine: { lineStyle: { color: dark ? '#51402B' : '#cbd5e1' } },
      },
      yAxis: {
        type: 'value',
        minInterval: 1,
        scale: true,
        axisLabel: { color: dark ? '#B39F73' : '#64748b' },
        splitLine: { lineStyle: { color: dark ? '#3a2e1c' : '#edf2f0' } },
      },
      series: [
        { name: '当日新任务', type: 'line', smooth: true, data: tasks, symbolSize: 5,
          lineStyle: { width: 2 }, itemStyle: { color: '#1E3A8A' }, areaStyle: { color: '#1E3A8A18' } },
        { name: '工具执行次数', type: 'line', smooth: true, data: ops, symbolSize: 5,
          lineStyle: { width: 2 }, itemStyle: { color: '#10b981' }, areaStyle: { color: '#10b98118' } },
      ],
    };
  }, [data, dark]);

  useEffect(() => {
    inst.current?.setOption(option, true);
  }, [option]);

  return <div ref={wrapper} style={{ width: '100%', height: 250 }} />;
}

function ToolCallTable({ items }: { items: any[] }) {
  const maxCount = Math.max(1, ...items.map((b) => b.count || 0));
  const cols = [
    { title: '工具动作', dataIndex: 'action', key: 'action', render: (v: string) => <span style={{ fontSize: 13 }}>{v}</span> },
    { title: '调用次数', dataIndex: 'count', key: 'count', width: 76, render: (v: number) => <b>{v}</b> },
    { title: '成功', dataIndex: 'success', key: 'success', width: 64, render: (v: number, r: any) => (
        <span style={{
          color: r.count !== r.success ? '#dc2626' : '#16a34a',
          fontWeight: r.count !== r.success ? 700 : undefined,
          fontSize: 13,
        }}>{v}</span>
      ) },
    { title: '成功占比', key: 'rate', width: 120, render: (_: any, r: any) => {
        const rate = r.count ? Math.round(((r.success || 0) / r.count) * 100) : 0;
        const bad = r.count !== r.success;
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Progress percent={rate} size="small" showInfo={false} strokeColor={bad ? '#dc2626' : '#16a34a'} style={{ flex: 1 }} />
            <span style={{ fontSize: 11, fontWeight: bad ? 700 : undefined, color: bad ? '#dc2626' : 'var(--muted)', width: 30 }}>{rate}%</span>
          </div>
        );
      } },
  ];
  return (
    <div>
      <Tooltip title="按工具动作统计的调用明细">
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 8 }}>
          <DatabaseOutlined style={{ marginRight: 6 }} />工具调用情况
        </div>
      </Tooltip>
      <Table
        rowKey="action"
        dataSource={items}
        columns={cols as any}
        size="small"
        pagination={false}
        scroll={{ y: 180 }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无工具调用" /> }}
        onRow={() => ({ style: { background: 'transparent' } })}
        rowClassName="dash-tool-row"
      />
    </div>
  );
}

function KbPanel({ kb, retrieval }: { kb: any; retrieval?: number }) {
  const items = [
    { label: '知识文档', value: kb.docs ?? 0 },
    { label: '知识片段', value: kb.chunks ?? 0 },
    { label: '知识库检索', value: retrieval ?? 0 },
  ];
  return (
    <div>
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 8 }}>
        <BookOutlined style={{ marginRight: 6 }} />知识库概况
      </div>
      <Row gutter={[8, 8]}>
        {items.map((it) => (
          <Col span={8} key={it.label}>
            <div style={{ background: 'var(--surface-2)', borderRadius: 8, padding: '10px 12px' }}>
              <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--text)', lineHeight: 1.1 }}>{it.value}</div>
              <div style={{ fontSize: 12, color: 'var(--muted-2)', marginTop: 4 }}>{it.label}</div>
            </div>
          </Col>
        ))}
      </Row>
      <div style={{ fontSize: 12, color: 'var(--muted-2)', marginTop: 8 }}>
        知识库检索次数在每次 RAG 召回时累计，反映问答/分析对知识图谱的依赖程度。
      </div>
    </div>
  );
}