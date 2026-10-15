import { Component, type ReactNode } from "react";

/** 画风工坊自己在浏览器里存的状态（打开的工作区、配方、筛选、草稿备份等）。 */
const LOCAL_PREFIX = "promptatelier.style-lab.";

type State = { error: Error | null; stack: string | null };

/**
 * 画风工坊出错时不再整页白屏：显示错误内容，可以重试，或清掉画风工坊的本地状态后重试
 * （工作区、配方、图片都在后端，不受影响）。
 */
export class StyleLabErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null, stack: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: { componentStack?: string | null }) {
    console.error("[style-lab]", error, info.componentStack);
    this.setState({ stack: info.componentStack ?? null });
  }

  private resetLocal = () => {
    try {
      Object.keys(window.localStorage)
        .filter((key) => key.startsWith(LOCAL_PREFIX))
        .forEach((key) => window.localStorage.removeItem(key));
    } catch {
      // 读不了本地存储就直接重试。
    }
    window.location.reload();
  };

  render() {
    const { error, stack } = this.state;
    if (!error) return this.props.children;
    const detail = [`${error.name}: ${error.message}`, error.stack, stack].filter(Boolean).join("\n\n");
    return (
      <main className="sl-crash" role="alert">
        <h2>画风工坊出错了</h2>
        <p>可以先重试；还不行就清掉画风工坊在这个浏览器里记住的状态（打开的工作区、配方、筛选等）再重试，后端的工作区、配方和图片不受影响。</p>
        <div className="sl-crash-actions">
          <button className="sl-primary small" onClick={() => this.setState({ error: null, stack: null })} type="button">
            重试
          </button>
          <button className="sl-ghost" onClick={this.resetLocal} type="button">
            清空本地状态后重试
          </button>
          <button className="sl-ghost" onClick={() => void navigator.clipboard?.writeText(detail)} type="button">
            复制错误信息
          </button>
        </div>
        <pre className="sl-crash-detail">{detail}</pre>
      </main>
    );
  }
}
