import { Component } from 'react';
import type { ReactNode } from 'react';
import { Alert } from 'antd';

/** 单条消息/卡片渲染兜底：任何渲染异常只降级本卡片，绝不整页白屏 */
export default class ErrorBoundary extends Component<
  { children: ReactNode; label?: string },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <Alert
          type="warning"
          showIcon
          message="该条内容渲染失败"
          description={this.props.label || '内容已跳过展示，其余对话正常。'}
          style={{ marginTop: 8 }}
        />
      );
    }
    return this.props.children;
  }
}