import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props { children: ReactNode; fallbackRoute?: string }
interface State { hasError: boolean; errorMsg: string }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, errorMsg: '' }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, errorMsg: error.message ?? 'Unknown error' }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Emit to console — backend telemetry can pick this up via window.onerror hooks
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 400, padding: 40, textAlign: 'center', gap: 16 }}>
        <div style={{ width: 48, height: 48, borderRadius: 'var(--r-3)', background: 'var(--neg-soft)', display: 'grid', placeItems: 'center', fontSize: 22 }}>
          ⚠
        </div>
        <h2 className="serif" style={{ fontSize: 24, fontWeight: 400, color: 'var(--ink-0)', margin: 0 }}>
          Something went wrong
        </h2>
        <p className="t-sm fg-2" style={{ maxWidth: 360, lineHeight: 1.6 }}>
          This part of the app crashed. Your data is safe — reload the page to continue.
        </p>
        {this.state.errorMsg && (
          <code style={{ fontSize: 11, color: 'var(--ink-3)', background: 'var(--paper-2)', padding: '4px 10px', borderRadius: 'var(--r-1)', maxWidth: 420, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {this.state.errorMsg}
          </code>
        )}
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <button
            onClick={() => window.location.reload()}
            style={{ padding: '8px 18px', fontSize: 13, fontFamily: 'inherit', cursor: 'pointer', background: 'var(--ink-0)', color: 'var(--paper-0)', border: 0, borderRadius: 'var(--r-2)', fontWeight: 500 }}
          >
            Reload page
          </button>
          {this.props.fallbackRoute && (
            <button
              onClick={() => { this.setState({ hasError: false, errorMsg: '' }); window.location.href = this.props.fallbackRoute! }}
              style={{ padding: '8px 18px', fontSize: 13, fontFamily: 'inherit', cursor: 'pointer', background: 'none', color: 'var(--ink-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)' }}
            >
              Go home
            </button>
          )}
        </div>
      </div>
    )
  }
}
