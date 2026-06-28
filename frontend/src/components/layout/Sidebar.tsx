import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { Icon } from '@/components/ui/Icon'
import { AgentPill } from '@/components/ui/AgentPill'
import { Avatar } from '@/components/ui/Avatar'
import { useLearnerStore } from '@/stores/learnerStore'
import { useAgentStore } from '@/stores/agentStore'
import { useThemeStore } from '@/stores/themeStore'
import { useCmdkStore } from '@/stores/cmdkStore'
import { useUiStore } from '@/stores/uiStore'
import { authAPI, setAccessToken } from '@/lib/api'
import { cn } from '@/lib/cn'

interface NavItem { id: string; label: string; icon: string; kbd?: string }
interface NavGroup { group: string; items: NavItem[] }

const NAV_GROUPS: NavGroup[] = [
  {
    group: 'Workspace',
    items: [
      { id: '/dashboard',  label: 'Dashboard',       icon: 'home',      kbd: 'D' },
      { id: '/learn',      label: 'Career Feed',      icon: 'feed',      kbd: 'T' },
      { id: '/atelier',    label: 'AI Assistant',     icon: 'sparkle',   kbd: 'A' },
      { id: '/interview',  label: 'Interview Coach',  icon: 'interview', kbd: 'V' },
    ],
  },
  {
    group: 'Career Tools',
    items: [
      { id: '/courses',   label: 'Career Paths',    icon: 'course' },
      { id: '/doubts',    label: 'Career Coach',    icon: 'chat' },
      { id: '/tracker',   label: 'Job Tracker',     icon: 'progress' },
    ],
  },
  {
    group: 'Insights',
    items: [
      { id: '/progress',   label: 'Readiness',  icon: 'progress' },
      { id: '/flashcards', label: 'Flashcards', icon: 'cards' },
    ],
  },
  {
    group: 'System',
    items: [
      { id: '/profile',   label: 'Profile',    icon: 'user' },
      { id: '/admin',     label: 'Admin',      icon: 'admin' },
    ],
  },
]

// Superuser-only nav item (evals dashboard), appended to the System group when applicable.
const EVALS_ITEM: NavItem = { id: '/evals', label: 'Agent Evals', icon: 'target' }

const AGENT_KEYS = ['curr', 'quiz', 'prog', 'doubt'] as const
const AGENT_MAP = { curr: 'curriculum', quiz: 'quiz', prog: 'progress', doubt: 'doubt' } as const

export function Sidebar() {
  const location = useLocation()
  const navigate = useNavigate()
  const { name, xp, streak, reset } = useLearnerStore()
  const role = useLearnerStore((s) => s.role)
  // Superuser sees an extra "Agent Evals" item in the System group.
  const navGroups: NavGroup[] = role === 'superuser'
    ? NAV_GROUPS.map((g) => (g.group === 'System' ? { ...g, items: [...g.items, EVALS_ITEM] } : g))
    : NAV_GROUPS
  const agents = useAgentStore((s) => s.agents)
  const { theme, toggleTheme } = useThemeStore()
  const openCmdk = useCmdkStore((s) => s.setOpen)
  const sidebarOpen = useUiStore((s) => s.sidebarOpen)
  const setSidebarOpen = useUiStore((s) => s.setSidebarOpen)

  // Close the mobile drawer whenever the route changes
  useEffect(() => {
    setSidebarOpen(false)
  }, [location.pathname, setSidebarOpen])

  const handleLogout = async () => {
    try { await authAPI.logout() } catch { /* ignore */ }
    setAccessToken(null)
    reset()
    toast.success('Signed out.')
    navigate('/')
  }

  return (
    <>
      {/* Mobile drawer backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 lg:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 w-[var(--sidebar-w)] transition-transform duration-[var(--dur-base)] ease-[var(--ease-out)]',
          'lg:static lg:z-auto lg:w-[var(--rail-w)] lg:translate-x-0 xl:w-[var(--sidebar-w)]',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        )}
        style={{
          background: 'var(--paper-1)',
          borderRight: '1px solid var(--line-1)',
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          overflow: 'hidden',
        }}
      >
        {/* Brand */}
        <div className="lg:justify-center xl:justify-start" style={{ padding: '14px 14px 10px', display: 'flex', alignItems: 'center', gap: 10 }}>
          <div
            style={{
              width: 24,
              height: 24,
              borderRadius: 6,
              background: 'var(--ink-0)',
              color: 'var(--paper-0)',
              display: 'grid',
              placeItems: 'center',
              fontFamily: 'var(--font-serif)',
              fontSize: 14,
              fontStyle: 'italic',
              flexShrink: 0,
            }}
          >
            æ
          </div>
          <div className="lg:hidden xl:block" style={{ flex: 1 }}>
            <div className="t-md" style={{ fontWeight: 600, color: 'var(--ink-0)', letterSpacing: '-0.01em' }}>Atelier</div>
            <div className="t-xs fg-3">AI Tutor</div>
          </div>
          <button
            title="Toggle theme"
            aria-label="Toggle theme"
            onClick={toggleTheme}
            className="lg:hidden xl:inline-flex"
            style={{ padding: 4, color: 'var(--ink-2)' }}
          >
            <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={14} />
          </button>
        </div>

        {/* Search / ⌘K */}
        <div style={{ padding: '4px 10px 10px' }}>
          <button
            onClick={() => openCmdk(true)}
            aria-label="Open search"
            className="lg:justify-center xl:justify-start"
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '5px 8px',
              background: 'var(--paper-0)',
              border: '1px solid var(--line-1)',
              borderRadius: 'var(--r-2)',
              fontSize: 12,
              color: 'var(--ink-3)',
              textAlign: 'left',
              cursor: 'pointer',
            }}
          >
            <Icon name="search" size={12} />
            <span className="lg:hidden xl:block" style={{ flex: 1 }}>Search or jump to…</span>
            <span className="inline-flex lg:hidden xl:inline-flex" style={{ gap: 2 }}>
              <kbd>⌘</kbd><kbd>K</kbd>
            </span>
          </button>
        </div>

        {/* Learner profile */}
        {name && (
          <div
            className="flex lg:hidden xl:flex"
            style={{
              margin: '0 8px 8px',
              padding: 8,
              borderRadius: 'var(--r-2)',
              background: 'var(--paper-0)',
              border: '1px solid var(--line-1)',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <Avatar name={name} size={26} status="online" />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="t-sm" style={{ fontWeight: 500, color: 'var(--ink-0)' }}>{name}</div>
              <div className="t-xs fg-3" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                  <Icon name="flame" size={10} /> {streak}d
                </span>
                <span>·</span>
                <span>L{Math.floor(xp / 500) + 1}</span>
                <span>·</span>
                <span>{xp.toLocaleString()} XP</span>
              </div>
            </div>
          </div>
        )}

        {/* Nav */}
        <nav aria-label="Main navigation" style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }}>
          {navGroups.map((grp) => (
            <div key={grp.group} style={{ marginBottom: 14 }}>
              <div className="caps lg:hidden xl:block" style={{ padding: '4px 8px', color: 'var(--ink-3)' }}>{grp.group}</div>
              {grp.items.map((it) => {
                const active = location.pathname === it.id || (it.id !== '/dashboard' && location.pathname.startsWith(it.id))
                return (
                  <button
                    key={it.id}
                    onClick={() => navigate(it.id)}
                    className="nav-i lg:justify-center xl:justify-start"
                    aria-current={active ? 'page' : undefined}
                    title={it.label}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      width: '100%',
                      padding: '5px 8px',
                      borderRadius: 'var(--r-2)',
                      background: active ? 'var(--paper-3)' : 'transparent',
                      color: active ? 'var(--ink-0)' : 'var(--ink-1)',
                      fontSize: 13,
                      fontWeight: active ? 500 : 400,
                      marginBottom: 1,
                      position: 'relative',
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                      border: 0,
                      textAlign: 'left',
                    }}
                    onMouseEnter={(e) => !active && (e.currentTarget.style.background = 'var(--paper-2)')}
                    onMouseLeave={(e) => !active && (e.currentTarget.style.background = 'transparent')}
                  >
                    {active && (
                      <div
                        style={{
                          position: 'absolute',
                          left: -8,
                          top: 4,
                          bottom: 4,
                          width: 2,
                          background: 'var(--accent)',
                          borderRadius: 2,
                        }}
                      />
                    )}
                    <Icon
                      name={it.icon}
                      size={14}
                      className="nav-i-icon"
                      style={{ color: active ? 'var(--ink-0)' : 'var(--ink-2)' }}
                    />
                    <span className="lg:hidden xl:block" style={{ flex: 1 }}>{it.label}</span>
                    {it.kbd && (
                      <span className="lg:hidden xl:inline" style={{ fontSize: 11, color: 'var(--ink-3)', fontFamily: 'var(--font-mono)' }}>{it.kbd}</span>
                    )}
                  </button>
                )
              })}
            </div>
          ))}
        </nav>

        {/* Agents footer */}
        <div style={{ padding: 10, borderTop: '1px solid var(--line-1)', background: 'var(--paper-0)' }}>
          <div className="caps lg:hidden xl:block" style={{ marginBottom: 6, color: 'var(--ink-3)' }}>Agents</div>
          <div className="flex lg:hidden xl:flex" style={{ flexWrap: 'wrap', gap: 4 }}>
            {AGENT_KEYS.map((k) => {
              const storeKey = AGENT_MAP[k]
              const s = agents[storeKey]?.status
              const state = s === 'active' ? 'active' : s === 'processing' ? 'thinking' : 'idle'
              return <AgentPill key={k} kind={k} state={state} mini />
            })}
          </div>

          {/* Logout */}
          <button
            onClick={handleLogout}
            aria-label="Sign out"
            title="Sign out"
            className="lg:justify-center xl:justify-start"
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              width: '100%', marginTop: 8, padding: '5px 6px',
              background: 'none', border: 0, borderRadius: 'var(--r-2)',
              color: 'var(--ink-3)', fontSize: 12, cursor: 'pointer',
              fontFamily: 'inherit', textAlign: 'left',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--paper-2)'; e.currentTarget.style.color = 'var(--neg)' }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'none'; e.currentTarget.style.color = 'var(--ink-3)' }}
          >
            <Icon name="logout" size={13} />
            <span className="lg:hidden xl:inline">Sign out</span>
          </button>
        </div>
      </aside>
    </>
  )
}
