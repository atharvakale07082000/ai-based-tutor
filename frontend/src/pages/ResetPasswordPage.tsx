import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import { authAPI } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'

const inputStyle: React.CSSProperties = {
  display: 'block', width: '100%', marginTop: 5,
  padding: '9px 11px', fontSize: 14,
  background: 'var(--paper-0)', border: '1px solid var(--line-2)',
  borderRadius: 'var(--r-2)', color: 'var(--ink-0)',
  fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box',
}

export default function ResetPasswordPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const token = params.get('token') ?? ''

  const [password, setPassword] = useState('')
  const [confirm, setConfirm]   = useState('')
  const [showPass, setShowPass] = useState(false)
  const [loading, setLoading]   = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token) { toast.error('Invalid or missing reset token.'); return }
    if (password.length < 6) { toast.error('Password must be at least 6 characters.'); return }
    if (password !== confirm) { toast.error('Passwords do not match.'); return }

    setLoading(true)
    try {
      await authAPI.resetConfirm(token, password)
      toast.success('Password updated. Please sign in.')
      navigate('/')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg ?? 'Reset failed — the link may have expired.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--paper-bg)', padding: 24,
    }}>
      <div style={{
        width: '100%', maxWidth: 400,
        background: 'var(--paper-1)', border: '1px solid var(--line-1)',
        borderRadius: 'var(--r-3)', boxShadow: 'var(--shadow-md)',
        overflow: 'hidden',
        animation: 'fadeSlideUp 0.18s ease',
      }}>
        {/* Header */}
        <div style={{ padding: '20px 24px 16px', borderBottom: '1px solid var(--line-1)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="serif" style={{ fontSize: 20, fontWeight: 400, color: 'var(--ink-0)' }}>
              Atelier
            </span>
          </div>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <h2 className="serif" style={{ fontSize: 22, fontWeight: 400, margin: '0 0 4px', color: 'var(--ink-0)' }}>
              Set a new password.
            </h2>
            <p className="t-sm fg-2">Choose something secure and memorable.</p>
          </div>

          {!token && (
            <div style={{ padding: '12px 14px', background: 'rgba(220,38,38,0.08)', border: '1px solid rgba(220,38,38,0.2)', borderRadius: 'var(--r-2)', fontSize: 13, color: 'var(--ink-1)' }}>
              This reset link is invalid or missing a token. Please request a new one.
            </div>
          )}

          <div>
            <label className="caps" style={{ color: 'var(--ink-2)', fontSize: 10 }}>New password</label>
            <div style={{ position: 'relative', marginTop: 5 }}>
              <input
                type={showPass ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Min 6 characters"
                required
                minLength={6}
                maxLength={128}
                autoComplete="new-password"
                autoFocus
                style={{ ...inputStyle, paddingRight: 38, marginTop: 0 }}
                onFocus={(e) => (e.target.style.borderColor = 'var(--ink-1)')}
                onBlur={(e)  => (e.target.style.borderColor = 'var(--line-2)')}
              />
              <button
                type="button"
                tabIndex={-1}
                onClick={() => setShowPass((v) => !v)}
                style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 0, cursor: 'pointer', padding: 2, color: 'var(--ink-3)' }}
              >
                <Icon name={showPass ? 'eye-off' : 'eye'} size={14} />
              </button>
            </div>
          </div>

          <div>
            <label className="caps" style={{ color: 'var(--ink-2)', fontSize: 10 }}>Confirm password</label>
            <input
              type={showPass ? 'text' : 'password'}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="Repeat your password"
              required
              maxLength={128}
              autoComplete="new-password"
              style={inputStyle}
              onFocus={(e) => (e.target.style.borderColor = 'var(--ink-1)')}
              onBlur={(e)  => (e.target.style.borderColor = 'var(--line-2)')}
            />
          </div>

          <Button type="submit" variant="primary" loading={loading} disabled={!token} style={{ width: '100%', marginTop: 4 }}>
            {loading ? 'Updating…' : 'Update password'}
          </Button>

          <p className="t-xs fg-3" style={{ textAlign: 'center', marginTop: 4 }}>
            <button type="button" onClick={() => navigate('/')} style={{ color: 'var(--accent)', background: 'none', border: 0, cursor: 'pointer', fontFamily: 'inherit', fontSize: 'inherit', padding: 0 }}>
              ← Back to sign in
            </button>
          </p>
        </form>
      </div>
    </div>
  )
}
