import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Icon } from '@/components/ui/Icon'
import { Badge } from '@/components/ui/Badge'
import { useCmdkStore } from '@/stores/cmdkStore'

const CMD_ACTIONS = [
  {
    group: 'Navigate',
    items: [
      { id: 'go-dashboard', label: 'Go to Dashboard',   icon: 'home',      target: '/dashboard' },
      { id: 'go-feed',      label: 'Go to Today',       icon: 'feed',      target: '/learn' },
      { id: 'go-doubts',    label: 'Open Doubt Chat',   icon: 'chat',      target: '/doubts' },
      { id: 'go-progress',  label: 'View Progress',     icon: 'progress',  target: '/progress' },
      { id: 'go-courses',   label: 'My Courses',        icon: 'course',    target: '/courses' },
      { id: 'go-assistant', label: 'Open AI Assistant', icon: 'sparkle',   target: '/atelier' },
      { id: 'go-interview', label: 'Interview Coach',   icon: 'interview', target: '/interview' },
      { id: 'go-tracker',   label: 'Job Tracker',       icon: 'progress',  target: '/tracker' },
    ],
  },
  {
    group: 'Actions',
    items: [
      { id: 'ask',       label: 'Ask a doubt…',                  icon: 'chat',      tag: 'Learning Assistant', target: '/doubts' },
      { id: 'plan',      label: 'Plan a new course',             icon: 'plus',      tag: 'Learning Path',      target: '/courses' },
      { id: 'interview', label: 'Start mock interview',          icon: 'interview', tag: 'Quiz Creator',       target: null },
      { id: 'progress',  label: 'View skill breakdown',          icon: 'target',    tag: null,           target: '/progress' },
    ],
  },
]

interface FlatItem {
  id: string
  label: string
  icon: string
  tag?: string | null
  target: string | null
  group: string
}

export function CommandPalette() {
  const { open, query, setOpen, setQuery } = useCmdkStore()
  const [sel, setSel] = useState(0)
  const navigate = useNavigate()

  const flat = useMemo<FlatItem[]>(() => {
    const all: FlatItem[] = []
    CMD_ACTIONS.forEach((grp) => grp.items.forEach((it) => all.push({ ...it, group: grp.group })))
    if (!query) return all
    return all.filter((it) => it.label.toLowerCase().includes(query.toLowerCase()))
  }, [query])

  useEffect(() => { setSel(0) }, [query])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); setOpen(true) }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [setOpen])

  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setOpen(false) }
      if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(s + 1, flat.length - 1)) }
      if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)) }
      if (e.key === 'Enter') {
        const item = flat[sel]
        if (item?.target) navigate(item.target)
        setOpen(false)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, flat, sel, navigate, setOpen])

  if (!open) return null

  const seenGroups = new Set<string>()

  return (
    <div
      onClick={() => setOpen(false)}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(20,17,13,0.45)',
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'center',
        paddingTop: '12vh',
        zIndex: 200,
        animation: 'fadeIn 0.15s var(--ease-out)',
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onClick={(e) => e.stopPropagation()}
        className="w-[92vw] sm:w-[560px]"
        style={{
          maxHeight: '70vh',
          background: 'var(--paper-0)',
          border: '1px solid var(--line-2)',
          borderRadius: 'var(--r-4)',
          boxShadow: 'var(--shadow-4)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          animation: 'fadeUp 0.2s var(--ease-out)',
        }}
      >
        {/* Search input */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px', borderBottom: '1px solid var(--line-1)' }}>
          <Icon name="search" size={14} style={{ color: 'var(--ink-3)' }} />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search actions, navigate, ask AI…"
            aria-label="Search actions and pages"
            role="combobox"
            aria-expanded="true"
            aria-controls="cmdk-results"
            aria-activedescendant={flat[sel] ? `cmdk-option-${flat[sel].id}` : undefined}
            style={{
              flex: 1,
              border: 0,
              outline: 'none',
              background: 'transparent',
              fontSize: 14,
              color: 'var(--ink-0)',
              fontFamily: 'inherit',
            }}
          />
          <Badge tone="accent" size="xs" icon="sparkle">AI</Badge>
          <kbd>ESC</kbd>
        </div>

        {/* AI suggestion strip */}
        {query && (
          <div style={{ padding: '7px 14px', borderBottom: '1px solid var(--line-1)', background: 'var(--accent-soft)', display: 'flex', gap: 8, alignItems: 'center' }}>
            <Icon name="sparkle" size={12} style={{ color: 'var(--accent)' }} />
            <span className="t-sm" style={{ color: 'var(--accent)', flex: 1 }}>Ask AI: "{query}"</span>
            <span style={{ display: 'inline-flex', gap: 2 }}><kbd>⌘</kbd><kbd>↵</kbd></span>
          </div>
        )}

        {/* Results */}
        <div id="cmdk-results" role="listbox" aria-label="Results" style={{ overflowY: 'auto', maxHeight: 400, padding: '6px 0' }}>
          {flat.length === 0 && (
            <div className="t-sm fg-3" style={{ padding: 24, textAlign: 'center' }}>No matches.</div>
          )}
          {flat.map((it, i) => {
            const showGroup = !seenGroups.has(it.group)
            seenGroups.add(it.group)
            return (
              <div key={it.id}>
                {showGroup && (
                  <div className="caps" style={{ padding: '8px 14px 4px', color: 'var(--ink-3)' }}>{it.group}</div>
                )}
                <div
                  id={`cmdk-option-${it.id}`}
                  role="option"
                  aria-selected={i === sel}
                  style={{
                    padding: '7px 14px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    background: i === sel ? 'var(--paper-2)' : 'transparent',
                    cursor: 'pointer',
                  }}
                  onClick={() => { if (it.target) navigate(it.target); setOpen(false) }}
                  onMouseEnter={() => setSel(i)}
                >
                  <Icon name={it.icon} size={14} style={{ color: 'var(--ink-2)' }} />
                  <span className="t-md fg-0" style={{ flex: 1 }}>{it.label}</span>
                  {it.tag && <Badge tone="outline" size="xs">{it.tag}</Badge>}
                  {i === sel && <kbd>↵</kbd>}
                </div>
              </div>
            )
          })}
        </div>

        {/* Footer */}
        <div style={{ padding: '8px 14px', borderTop: '1px solid var(--line-1)', display: 'flex', gap: 12, fontSize: 11, color: 'var(--ink-3)' }}>
          <span><kbd>↑</kbd> <kbd>↓</kbd> navigate</span>
          <span><kbd>↵</kbd> select</span>
          <span style={{ marginLeft: 'auto' }}>Powered by 4 agents</span>
        </div>
      </div>
    </div>
  )
}
