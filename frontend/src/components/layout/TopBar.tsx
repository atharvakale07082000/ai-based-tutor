import { useLocation, useNavigate } from 'react-router-dom'
import { Icon } from '@/components/ui/Icon'
import { Button } from '@/components/ui/Button'
import { useLearnerStore } from '@/stores/learnerStore'
import { useCmdkStore } from '@/stores/cmdkStore'
import { useUiStore } from '@/stores/uiStore'
import { authAPI } from '@/lib/api'

const BREADCRUMBS: Record<string, string[]> = {
  '/dashboard':  ['Dashboard'],
  '/learn':      ['Today'],
  '/assistant':  ['Assistant'],
  '/courses':    ['Courses'],
  '/doubts':     ['Doubts'],
  '/progress':   ['Progress'],
  '/admin':      ['Admin', 'Agent Operations'],
  '/onboarding': ['Onboarding'],
}

function getBreadcrumbs(pathname: string): string[] {
  const match = Object.entries(BREADCRUMBS).find(([k]) => pathname === k || pathname.startsWith(k + '/'))
  return match ? match[1] : [pathname.replace('/', '')]
}

export function TopBar() {
  const location = useLocation()
  const navigate = useNavigate()
  const { name, reset } = useLearnerStore()
  const openCmdk = useCmdkStore((s) => s.setOpen)
  const toggleSidebar = useUiStore((s) => s.toggleSidebar)
  const crumbs = getBreadcrumbs(location.pathname)

  const handleLogout = async () => {
    try { await authAPI.logout() } catch {}
    reset()
    navigate('/')
  }

  return (
    <div
      style={{
        height: 'var(--topbar-h)',
        padding: '0 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        background: 'var(--paper-0)',
        borderBottom: '1px solid var(--line-1)',
        flexShrink: 0,
      }}
    >
      {/* Mobile sidebar toggle */}
      <button
        onClick={toggleSidebar}
        aria-label="Toggle navigation menu"
        className="lg:hidden"
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 28, height: 28, padding: 6, color: 'var(--ink-2)', borderRadius: 'var(--r-1)', flexShrink: 0 }}
      >
        <Icon name="menu" size={16} />
      </button>

      {/* Breadcrumbs */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 0 }}>
        {crumbs.map((b, i) => (
          <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            {i > 0 && <Icon name="chevR" size={11} style={{ color: 'var(--ink-3)' }} />}
            <span
              className={i === crumbs.length - 1 ? 'fg-0' : 'fg-2'}
              style={{
                fontSize: 14,
                fontWeight: i === crumbs.length - 1 ? 500 : 400,
                whiteSpace: 'nowrap',
              }}
            >
              {b}
            </span>
          </span>
        ))}
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <button
          onClick={() => openCmdk(true)}
          aria-label="Open command palette"
          className="hidden sm:flex"
          style={{
            alignItems: 'center',
            gap: 6,
            padding: '4px 8px',
            background: 'var(--paper-1)',
            border: '1px solid var(--line-1)',
            borderRadius: 'var(--r-2)',
            fontSize: 12,
            color: 'var(--ink-3)',
            cursor: 'pointer',
          }}
        >
          <Icon name="search" size={12} />
          <span>⌘K</span>
        </button>

        <Button
          size="sm"
          variant="accent"
          icon="sparkle"
          className="hidden sm:inline-flex"
          onClick={() => navigate('/assistant')}
        >
          Ask Atelier
        </Button>

        <button
          title="Notifications"
          aria-label="Notifications"
          style={{ padding: 6, color: 'var(--ink-2)', borderRadius: 'var(--r-1)', lineHeight: 0 }}
        >
          <Icon name="bell" size={14} />
        </button>

        <button
          onClick={handleLogout}
          title={name ? `Logout ${name}` : 'Logout'}
          aria-label={name ? `Logout ${name}` : 'Logout'}
          style={{
            width: 26,
            height: 26,
            borderRadius: 'var(--r-pill)',
            background: 'var(--ink-0)',
            color: 'var(--paper-0)',
            display: 'grid',
            placeItems: 'center',
            fontFamily: 'var(--font-serif)',
            fontSize: 12,
            fontStyle: 'italic',
            cursor: 'pointer',
          }}
        >
          {name ? name[0].toUpperCase() : 'æ'}
        </button>
      </div>
    </div>
  )
}
