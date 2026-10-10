import { Component, ErrorInfo, ReactNode } from "react";
import { Link } from "react-router-dom";

interface State {
  error: Error | null;
}

/** Keeps one broken page from blanking the whole app; resets when the route changes. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("GitShield UI error", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="page">
        <div className="state-card">
          <div className="state-art" aria-hidden>⚠️</div>
          <h1>Bu sayfa beklenmedik bir hatayla karşılaştı</h1>
          <p className="muted">Diğer sayfalar çalışmaya devam ediyor. Sayfayı yenilemek genelde yeterli.</p>
          <pre className="pre state-detail">{this.state.error.message}</pre>
          <div className="head-actions">
            <button className="btn btn-primary" onClick={() => window.location.reload()}>Sayfayı yenile</button>
            <Link className="btn" to="/">Genel bakışa dön</Link>
          </div>
        </div>
      </div>
    );
  }
}

export function NotFoundPage() {
  return (
    <div className="page">
      <div className="state-card">
        <div className="state-art" aria-hidden>🧭</div>
        <h1>Bu sayfa bulunamadı</h1>
        <p className="muted">Adres yanlış yazılmış ya da sayfa taşınmış olabilir.</p>
        <div className="head-actions">
          <Link className="btn btn-primary" to="/">Genel bakış</Link>
          <Link className="btn" to="/inbox">Bekleyenler</Link>
        </div>
      </div>
    </div>
  );
}
