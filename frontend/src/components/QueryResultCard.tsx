import { useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { Collapse, Tag, Space, Table, Typography } from 'antd';
import type { EChartsOption } from 'echarts';
import { useThemeMode } from '../theme';

interface Series {
  name: string;
  data: number[];
}
interface ChartData {
  table: string;
  table_label: string;
  dimension_label: string;
  categories: string[];
  series: Series[];
  suggested: string;
  types: string[];
}
interface Analysis {
  table: string;
  sql?: string;
  sql_params?: Record<string, unknown>;
  chart?: ChartData;
  raw?: boolean;
  rows?: Record<string, unknown>[];
  dimension_label?: string;
  measures?: { name: string; label: string }[];
}

const TYPE_LABEL: Record<string, string> = {
  bar: '柱状图',
  line: '折线图',
  pie: '饼图',
  area: '面积图',
  stack: '堆积图',
};

function buildOption(chart: ChartData, type: string, dark: boolean): EChartsOption {
  const cats = chart.categories || [];
  const axisLabelColor = dark ? '#B39F73' : '#64748b';
  const axisLineColor = dark ? '#51402B' : '#cbd5e1';
  const splitLineColor = dark ? '#3a2e1c' : '#edf2f0';
  const legendColor = dark ? '#CBB98E' : '#475569';
  const base: EChartsOption = {
    tooltip: { trigger: 'axis' },
    legend: chart.series.length > 1 ? { type: 'scroll', bottom: 0, textStyle: { color: legendColor } } : undefined,
    grid: { left: 8, right: 24, top: 28, bottom: 32, containLabel: true },
  };
  if (type === 'pie') {
    const s0 = chart.series[0] || { data: [] };
    return {
      ...base,
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { type: 'scroll', bottom: 0, textStyle: { color: legendColor } },
      series: [
        {
          type: 'pie',
          radius: ['35%', '68%'],
          center: ['50%', '46%'],
          data: cats.map((c, i) => ({ name: c, value: (s0.data || [])[i] || 0 })),
          label: { formatter: '{b}: {c}', color: dark ? '#F3E7C9' : '#334155' },
          emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(0,0,0,0.3)' } },
        },
      ],
    };
  }
  const st = type === 'stack';
  const dynamic = !st; // 堆积图从 0 起语义更清晰，其余启用动态坐标轴（起点不强制 0）
  const dual = chart.series.length >= 2 && !st; // 双指标 → 左右双 Y 轴
  const series = chart.series.map((s, i) => ({
    name: s.name,
    type: (type === 'line' || type === 'area' ? 'line' : 'bar') as 'line' | 'bar',
    smooth: type === 'line' || type === 'area',
    data: s.data,
    ...(st ? { stack: 'total' } : {}),
    ...(type === 'area' ? { areaStyle: {} } : {}),
    ...(dual ? { yAxisIndex: i } : {}),
  }));
  const valAxis = (abbr: boolean) => ({
    type: 'value' as const,
    ...(dynamic ? { scale: true } : {}),
    axisLabel: {
      color: axisLabelColor,
      ...(abbr
        ? { formatter: (v: number) => (Math.abs(v) >= 10000 ? `${(v / 10000).toFixed(1)}w` : String(v)) }
        : {}),
    },
    splitLine: { lineStyle: { color: splitLineColor } },
  });
  return {
    ...base,
    xAxis: {
      type: 'category',
      data: cats,
      axisLabel: { color: axisLabelColor },
      axisLine: { lineStyle: { color: axisLineColor } },
    },
    // 双轴须与系列一一对应：series 的 yAxisIndex 递增到 series.length-1，
    // 若 yAxis 轴多于 2 个系列则越界 → ECharts 抛 "yAxis not found" → 整树卸载白屏
    yAxis: dual ? chart.series.map(() => valAxis(true)) : valAxis(false),
    series,
  };
}

function EChart({ option, height = 280 }: { option: EChartsOption; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    const el = ref.current;
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
  useEffect(() => {
    try {
      inst.current?.setOption(option, true);
    } catch {
      /* 非法图表配置不抛给 React 渲染，避免整卡崩溃 */
    }
  }, [option]);
  return <div ref={ref} style={{ height, width: '100%' }} />;
}

export default function QueryResultCard({ data }: { data: Record<string, unknown> }) {
  const analyses = (data.analyses as Analysis[]) || [];
  const insight = (data.insight as { conclusion?: string; suggestions?: string[] }) || {};
  const followUps = (data.follow_ups as string[]) || [];

  if (analyses.length === 0) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 8 }}>
      {analyses.map((a, idx) =>
        a.chart ? (
          <ChartBlock key={idx} a={a} />
        ) : (
          <RawBlock key={idx} a={a} />
        )
      )}

      {(insight.conclusion || (insight.suggestions || []).length > 0) && (
        <div className="insight-card">
          {insight.conclusion && (
            <>
              <Typography.Text strong>📌 数据结论</Typography.Text>
              <div style={{ whiteSpace: 'pre-wrap', fontSize: 13, color: 'var(--text)', margin: '6px 0 10px' }}>
                {insight.conclusion}
              </div>
            </>
          )}
          {(insight.suggestions || []).length > 0 && (
            <>
              <Typography.Text strong>🚀 下一步建议</Typography.Text>
              <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 13, color: 'var(--muted)' }}>
                {(insight.suggestions || []).map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {followUps.length > 0 && (
        <div className="follow-card">
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>你可能还想问：</div>
          <div className="follow-list">
            {followUps.map((q, i) => (
              <FollowChip key={i} text={q} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function FollowChip({ text }: { text: string }) {
  return (
    <div
      className="follow-chip"
      title={text}
      onClick={() => window.dispatchEvent(new CustomEvent('honeydesk:ask', { detail: text }))}
    >
      {text}
    </div>
  );
}

function sanitizeChart(ch: any): ChartData {
  const series = (Array.isArray(ch.series) ? ch.series : []).filter(
    (s: any) => s && typeof s === 'object' && Array.isArray(s.data),
  );
  const types = Array.isArray(ch.types) ? ch.types.slice() : [];
  let suggested =
    typeof ch.suggested === 'string' && ch.suggested ? ch.suggested : 'bar';
  if (types.length > 0 && !types.includes(suggested)) suggested = types[0]; // 建议类型不在候选时回退
  return {
    ...(ch || {}),
    categories: Array.isArray(ch.categories) ? ch.categories.slice() : [],
    series,
    types,
    suggested,
  };
}

function ChartBlock({ a }: { a: Analysis }) {
  const chart = sanitizeChart(a.chart);
  const { resolved } = useThemeMode();
  const dark = resolved === 'dark';
  const [type, setType] = useState(chart.suggested);
  const option = useMemo(() => buildOption(chart, type, dark), [chart, type, dark]);
  return (
    <div className="chart-card">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <Typography.Text strong style={{ fontSize: 14 }}>
          📊 {chart.table_label} · {chart.dimension_label}
        </Typography.Text>
        <div style={{ flex: 1 }} />
        {chart.types.length > 1 && (
          <Space size={4} style={{ flexWrap: 'wrap' }}>
            {chart.types.map((t) => (
              <Tag
                key={t}
                color={t === type ? 'blue' : 'default'}
                style={{ cursor: 'pointer', margin: 0 }}
                onClick={() => setType(t)}
              >
                {TYPE_LABEL[t] || t}
              </Tag>
            ))}
          </Space>
        )}
      </div>
      <EChart option={option} />
      {a.sql && (
        <Collapse
          ghost
          size="small"
          style={{ marginTop: 2 }}
          items={[{
            key: 'sql',
            label: <span style={{ fontSize: 12, color: 'var(--muted)' }}>查看生成 SQL</span>,
            children: (
              <pre style={{ fontSize: 11, background: '#0f172a', color: '#e2e8f0', padding: 10, borderRadius: 8, overflow: 'auto' }}>
                {a.sql}
              </pre>
            ),
          }]}
        />
      )}
    </div>
  );
}

function RawBlock({ a }: { a: Analysis }) {
  const rows = a.rows || [];
  const cols = rows.length > 0 ? Object.keys(rows[0]) : [];
  return (
    <div className="chart-card">
      <Typography.Text strong style={{ fontSize: 14 }}>
        🗂 {a.table}（{rows.length} 条）
      </Typography.Text>
      {rows.length > 0 && (
        <Table
          size="small"
          style={{ marginTop: 8 }}
          rowKey={(_, i) => String(i)}
          dataSource={rows}
          columns={cols.map((k) => ({ title: k, dataIndex: k, ellipsis: true }))}
          scroll={{ x: 'max-content' }}
          pagination={{
            pageSize: 10,
            size: 'small',
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50],
            showTotal: (t, range) => `${range[0]}-${range[1]} / 共 ${t} 条`,
          }}
        />
      )}
      {a.sql && (
        <Collapse
          ghost
          size="small"
          style={{ marginTop: 2 }}
          items={[{ key: 'sql', label: <span style={{ fontSize: 12, color: 'var(--muted)' }}>查看生成 SQL</span>, children: <pre style={{ fontSize: 11, background: '#0f172a', color: '#e2e8f0', padding: 10, borderRadius: 8, overflow: 'auto' }}>{a.sql}</pre> }]}
        />
      )}
    </div>
  );
}