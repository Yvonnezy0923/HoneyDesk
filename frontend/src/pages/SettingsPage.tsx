import { useEffect, useState } from 'react';
import { Card, Form, Input, Button, Space, Alert, Tag, message, Spin, Descriptions, Radio } from 'antd';
import { SaveOutlined, ThunderboltOutlined, DatabaseOutlined, BgColorsOutlined } from '@ant-design/icons';
import { api } from '../api';
import { useThemeMode, type ThemeMode } from '../theme';

const THEME_OPTIONS = [
  { value: 'light', label: '微光·清新', hint: '浅色' },
  { value: 'dark', label: '臻选·醇厚', hint: '深色' },
  { value: 'system', label: '跟随系统', hint: '自动' },
] as const;

export default function SettingsPage() {
  const { mode, resolved, setMode } = useThemeMode();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<any>(null);
  const [embedding, setEmbedding] = useState('');
  const [loading, setLoading] = useState(true);
  const [maskedKey, setMaskedKey] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const r = await api.settings();
        const llm = r.llm || {};
        setEmbedding(r.embedding_backend || 'fallback');
        if (llm.api_key_masked) setMaskedKey(llm.api_key_masked);
        form.setFieldsValue({
          api_base: llm.api_base || '',
          api_key: '',
          model: llm.model || '',
          light_model: llm.light_model || '',
        });
      } finally {
        setLoading(false);
      }
    })();
  }, [form]);

  if (loading) return <Spin style={{ display: 'block', margin: '80px auto' }} />;

  return (
    <div style={{ maxWidth: 760 }}>
      <Card
        title={
          <Space>
            <BgColorsOutlined />
            <span>界面风格</span>
          </Space>
        }
        variant="borderless"
        style={{ marginBottom: 16 }}
      >
        <Radio.Group
          value={mode}
          onChange={(e) => setMode(e.target.value as ThemeMode)}
          optionType="button"
          buttonStyle="solid"
        >
          {THEME_OPTIONS.map((o) => (
            <Radio.Button key={o.value} value={o.value}>
              {o.label}
              <span style={{ opacity: 0.65, marginLeft: 4, fontSize: 12 }}>
                {o.hint}
              </span>
            </Radio.Button>
          ))}
        </Radio.Group>
        <div style={{ marginTop: 12 }}>
          <Tag color={resolved === 'dark' ? 'gold' : 'green'}>当前生效：{resolved === 'dark' ? '臻选·醇厚（深色）' : '微光·清新（浅色）'}</Tag>
          <span style={{ opacity: 0.65, fontSize: 12 }}>浅色与深色为两套独立配色，「跟随系统」会随操作系统的深浅色自动切换。</span>
        </div>
      </Card>

      <Card title="大模型（LLM）配置" variant="borderless" style={{ marginBottom: 16 }}>
        <Form
          form={form}
          layout="vertical"
          onFinish={async (v) => {
            setSaving(true);
            try {
              await api.saveLLM(v);
              message.success('LLM 配置已保存');
            } finally {
              setSaving(false);
            }
          }}
        >
          <Form.Item name="api_base" label="API Base（Endpoint）" rules={[{ required: true, message: '请输入 API 地址' }]}>
            <Input placeholder="https://api.openai.com/v1 或其它兼容网关" />
          </Form.Item>
          <Form.Item
            name="api_key"
            label={
              <Space>
                <span>API Key</span>
                {maskedKey && <Tag color="green">已配置 · {maskedKey}</Tag>}
              </Space>
            }
          >
            <Input.Password placeholder={maskedKey ? '留空表示保持不变' : 'sk-…'} autoComplete="off" />
          </Form.Item>
          <Form.Item name="model" label="主模型" rules={[{ required: true, message: '请输入模型名' }]}>
            <Input placeholder="gpt-4o / claude-3-5-sonnet / deepseek-chat" />
          </Form.Item>
          <Form.Item name="light_model" label="轻量模型（可选，用于路由/分类）">
            <Input placeholder="留空则使用主模型" />
          </Form.Item>
          <Space>
            <Button
              type="primary"
              htmlType="submit"
              loading={saving}
              icon={<SaveOutlined />}
            >
              保存配置
            </Button>
            <Button
              icon={<ThunderboltOutlined />}
              loading={testing}
              onClick={async () => {
                setTesting(true);
                setTestResult(null);
                try {
                  const r = await api.testLLM();
                  setTestResult(r);
                } finally {
                  setTesting(false);
                }
              }}
            >
              测试连接
            </Button>
          </Space>
        </Form>

        {testResult && (
          <Alert
            style={{ marginTop: 16 }}
            type={testResult.ok ? 'success' : 'error'}
            showIcon
            message={testResult.ok ? '连接成功' : '连接失败'}
            description={testResult.message || testResult.detail || ''}
          />
        )}
      </Card>

      <Card title="本地组件状态" variant="borderless">
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="文本向量化">
            <Tag color={embedding === 'fallback' ? 'orange' : 'green'}>
              {embedding === 'fallback' ? '本地 fallback（未加载 BGE-M3）' : `实际后端：${embedding}`}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="重排 Reranker">
            <Tag color="blue">BGE-reranker（cross-encoder）</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="检索方式">
            <Tag color="blue">BM25 + 向量 → RRF → Rerank</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="多 Agent 编排">
            <Tag color="blue">LangGraph</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="向量库">
            <Space size={4}><DatabaseOutlined /><span>Qdrant（本地 Docker）</span></Space>
          </Descriptions.Item>
          <Descriptions.Item label="业务/系统库">
            <Space size={4}><DatabaseOutlined /><span>MySQL 8.0（本机，非容器）</span></Space>
          </Descriptions.Item>
          <Descriptions.Item label="部署形态" span={2}>
            <Tag color="purple">本地优先 + Docker Compose（除 MySQL 外全容器）</Tag>
          </Descriptions.Item>
        </Descriptions>
      </Card>
    </div>
  );
}