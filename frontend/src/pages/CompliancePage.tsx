import { useState, useEffect } from 'react';
import { api } from '../api';

interface ComplianceData {
  approval_rate: number;
  approval_total: number;
  approval_pending: number;
  approval_approved: number;
  approval_rejected: number;
  unauthorized_writes: number;
  pii_blocks: number;
  memory_stats: { total: number; by_type: Record<string, number>; pii_flagged: number };
  data_retention: { audit_days: number; memory_ttl_days: number };
  gdpr_checklist: Array<{ item: string; status: string; description: string }>;
}

export default function CompliancePage() {
  const [data, setData] = useState<ComplianceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    api.complianceOverview().then(r => {
      setData(r);
      setLoading(false);
    }).catch(e => {
      setError(e?.message || '加载失败');
      setLoading(false);
    });
  }, []);

  if (loading) return <div className="p-6 text-gray-500">加载合规审计数据...</div>;
  if (error) return <div className="p-6 text-red-500">{error}</div>;
  if (!data) return <div className="p-6 text-gray-500">暂无数据</div>;

  const statusColor = (s: string) => {
    switch (s) {
      case 'pass': return 'bg-green-100 text-green-800';
      case 'fail': return 'bg-red-100 text-red-800';
      default: return 'bg-gray-100 text-gray-600';
    }
  };

  const handleExport = () => {
    api.complianceExport().then(blob => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `compliance_report_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    });
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-800">合规审计视图</h1>
        <button onClick={handleExport}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm">
          导出审计报告
        </button>
      </div>

      {/* 审批统计 */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <StatCard label="审批总数" value={data.approval_total} color="blue" />
        <StatCard label="通过率" value={`${data.approval_rate}%`} color="green" />
        <StatCard label="待审批" value={data.approval_pending} color="yellow" />
        <StatCard label="已拒绝" value={data.approval_rejected} color="red" />
        <StatCard label="未授权写入" value={data.unauthorized_writes} color={data.unauthorized_writes > 0 ? 'red' : 'green'} />
      </div>

      {/* PII 与记忆 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white rounded-xl shadow-sm border p-5">
          <h3 className="font-semibold text-gray-700 mb-3">PII 治理</h3>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-gray-500">PII 拦截数</span><span className="font-medium">{data.pii_blocks}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">记忆总数</span><span className="font-medium">{data.memory_stats?.total ?? 0}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">PII 标记条目</span><span className="font-medium">{data.memory_stats?.pii_flagged ?? 0}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">记忆保留期</span><span className="font-medium">{data.data_retention?.memory_ttl_days ?? 365} 天</span></div>
          </div>
        </div>
        <div className="bg-white rounded-xl shadow-sm border p-5">
          <h3 className="font-semibold text-gray-700 mb-3">数据保留</h3>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-gray-500">审计日志保留期</span><span className="font-medium">{data.data_retention?.audit_days ?? 365} 天</span></div>
            <div className="flex justify-between"><span className="text-gray-500">未授权写操作</span><span className={`font-medium ${data.unauthorized_writes > 0 ? 'text-red-600' : 'text-green-600'}`}>{data.unauthorized_writes}</span></div>
          </div>
        </div>
      </div>

      {/* GDPR 合规清单 */}
      <div className="bg-white rounded-xl shadow-sm border p-5">
        <h3 className="font-semibold text-gray-700 mb-3">GDPR 合规检查清单</h3>
        <div className="divide-y">
          {(data.gdpr_checklist || []).map((item, i) => (
            <div key={i} className="flex items-center gap-3 py-3">
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColor(item.status)}`}>
                {item.status === 'pass' ? '✓ 通过' : item.status === 'fail' ? '✗ 未通过' : '—'}
              </span>
              <div>
                <div className="font-medium text-sm text-gray-800">{item.item}</div>
                <div className="text-xs text-gray-500">{item.description}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string | number; color: string }) {
  const colors: Record<string, string> = {
    blue: 'bg-blue-50 border-blue-200 text-blue-700',
    green: 'bg-green-50 border-green-200 text-green-700',
    yellow: 'bg-yellow-50 border-yellow-200 text-yellow-700',
    red: 'bg-red-50 border-red-200 text-red-700',
  };
  return (
    <div className={`rounded-xl border p-4 ${colors[color] || colors.blue}`}>
      <div className="text-xs opacity-75">{label}</div>
      <div className="text-2xl font-bold mt-1">{value}</div>
    </div>
  );
}