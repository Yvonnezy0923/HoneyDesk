export interface ChatMessage {
  id: number;
  role: 'user' | 'assistant';
  agent_code: string;
  session_id?: string;
  content: string;
  task_id: string;
  data?: any;
  created_at: string;
}

export interface ChatSession {
  id: string;
  agent_code: string;
  title: string;
  created_at: string;
  last_message_at: string;
}

export interface Approval {
  id: string;
  op_id: string;
  task_id: string;
  agent_code: string;
  table_name: string;
  record_key: string;
  changes?: { _record?: Record<string, any>; [k: string]: any };
  reason: string;
  evidence: string;
  status: string;
  reviewer: string;
  review_note: string;
  created_at: string;
  timeout_at: string;
}

export interface Artifact {
  id: string;
  title: string;
  art_type: string;
  scope: string;
  agent_code: string;
  task_id: string;
  content: string;
  data?: any;
  sources?: any[];
  is_temp: boolean;
  expires_at: string;
  ttl_days?: number | null;
  expired: boolean;
  created_at: string;
}

export interface Tool {
  code: string;
  name: string;
  table_name: string;
  permission: string;
  scope: string;
  description: string;
  fields: { name: string; type: string }[];
  call_count: number;
  success_count: number;
}

export interface AgentMeta {
  name: string;      // 场景化名称（去“查询”误导）
  scope: string;
  desc: string;
  color: string;
  icon: string;
  caps: string[];    // 业务能力简介（对应“当前Agent能做什么”）
}

export const AGENTS: Record<string, AgentMeta> = {
  ops_query: {
    name: '运营 Agent', scope: 'operations', desc: '销售 / 商品 / 竞品 / 退货分析',
    color: '#5B9BD5', icon: '🛒',
    caps: [
      '销售、订单、退货的多维度汇总与趋势',
      '按 SKU、日期、市场下钻与对比',
      '竞品、排名与评价分析',
      '基于查询生成可注入的只读报告',
    ],
  },
  ops_listing: {
    name: 'Listing Agent', scope: 'operations', desc: 'Listing 生成与优化',
    color: '#34B7A3', icon: '📝',
    caps: [
      '读取产品资料生成 / 优化 Listing',
      '标题、五点、描述、关键词批量产出',
      '写操作生成审批，批准后落库',
      '沉淀为可跨 Agent 注入的产物',
    ],
  },
  supply_query: {
    name: '供应链 Agent', scope: 'supply', desc: '库存 / 在途 / 补货',
    color: '#9C7BD8', icon: '📦',
    caps: [
      '库存水位与安全库存核查',
      '在途数量与到货预估',
      '缺货风险与补货优先级建议',
      '按仓库、日期下钻分析',
    ],
  },
  ads_query: {
    name: '广告 Agent', scope: 'ads', desc: '广告花费 / ROI / 出价',
    color: '#E89A62', icon: '📣',
    caps: [
      '广告花费与预算执行情况',
      'ROI / ACOS / ROAS 分析',
      '转化率、CTR 下钻',
      '出价(bid)与预算调优建议',
    ],
  },
};