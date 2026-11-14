import { Component, type ReactNode } from "react";

type ErrorBoundaryState = {
  error: Error | null;
};

export class ErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(): void {}

  private reset = () => {
    this.setState({ error: null });
  };

  render() {
    if (this.state.error) {
      return (
        <div className="empty-state" role="alert">
          <h2>页面渲染失败</h2>
          <p>当前页面遇到错误，可以重试或切换页面</p>
          <button className="button" type="button" onClick={this.reset}>
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
