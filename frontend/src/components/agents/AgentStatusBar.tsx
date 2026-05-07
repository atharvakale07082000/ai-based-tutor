import { useAgentStore, type AgentStatus } from '@/stores/agentStore'
import { Badge } from '@/components/ui/Badge'

const AGENT_META = {
  curriculum: { label: 'Curriculum Planner', icon: '🗺️' },
  quiz: { label: 'Quiz Generator', icon: '📝' },
  progress: { label: 'Progress Tracker', icon: '📊' },
  doubt: { label: 'Doubt-Solver', icon: '💡' },
} as const

function statusVariant(status: AgentStatus['status']) {
  if (status === 'active') return 'emerald'
  if (status === 'processing') return 'amber'
  if (status === 'error') return 'rose'
  return 'surface'
}

function AgentCard({ agentKey }: { agentKey: keyof typeof AGENT_META }) {
  const agent = useAgentStore((s) => s.agents[agentKey])
  const meta = AGENT_META[agentKey]

  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-surface-2/60 border border-surface-3/50">
      <span className="text-base">{meta.icon}</span>
      <div className="flex flex-col gap-0.5 min-w-0">
        <span className="text-xs text-paper/70 truncate">{meta.label}</span>
        <Badge variant={statusVariant(agent.status)} dot glow={agent.status === 'active'} className="text-[10px] py-0.5 px-1.5">
          {agent.status}
        </Badge>
      </div>
      {agent.latencyMs > 0 && (
        <span className="text-[10px] text-paper/40 ml-auto">{agent.latencyMs}ms</span>
      )}
    </div>
  )
}

function HFStatusPill() {
  const hfModels = useAgentStore((s) => s.hfModels)
  const errorCount = Object.values(hfModels).filter((m) => m.status === 'error').length
  const loadingCount = Object.values(hfModels).filter((m) => m.status === 'loading').length

  const variant = errorCount > 0 ? 'rose' : loadingCount > 0 ? 'amber' : 'hf'

  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-surface-2/60 border border-surface-3/50">
      <span className="text-base">🤗</span>
      <div className="flex flex-col gap-0.5">
        <span className="text-xs text-paper/70">Hugging Face</span>
        <Badge variant={variant} dot className="text-[10px] py-0.5 px-1.5">
          {errorCount > 0 ? `${errorCount} error(s)` : loadingCount > 0 ? 'Loading…' : '8 models active'}
        </Badge>
      </div>
    </div>
  )
}

export function AgentStatusBar() {
  return (
    <div className="glass border-b border-surface-2/50 px-6 py-3">
      <div className="flex items-center gap-3 overflow-x-auto scrollbar-hide">
        <span className="text-xs text-paper/40 uppercase tracking-widest whitespace-nowrap mr-1">
          AI Agents
        </span>
        {(Object.keys(AGENT_META) as Array<keyof typeof AGENT_META>).map((key) => (
          <AgentCard key={key} agentKey={key} />
        ))}
        <div className="w-px h-8 bg-surface-3 mx-1" />
        <HFStatusPill />
      </div>
    </div>
  )
}
