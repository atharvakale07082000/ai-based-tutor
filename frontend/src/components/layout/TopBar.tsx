import { Link, useNavigate } from 'react-router-dom'
import { useLearnerStore } from '@/stores/learnerStore'
import { authAPI } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import toast from 'react-hot-toast'

export function TopBar() {
  const { name, xp, streak, reset } = useLearnerStore()
  const navigate = useNavigate()

  const handleLogout = async () => {
    try {
      await authAPI.logout()
    } catch {
      // best-effort
    }
    reset()
    navigate('/')
  }

  return (
    <header className="h-14 glass border-b border-surface-2/50 flex items-center px-6 gap-4 z-40 sticky top-0">
      {/* Logo */}
      <Link to="/dashboard" className="flex items-center gap-2 mr-4">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet to-indigo flex items-center justify-center text-white text-sm font-bold">
          AI
        </div>
        <span className="font-display font-semibold text-paper hidden sm:block">
          AI Tutor
        </span>
      </Link>

      {/* Nav Links */}
      <nav className="hidden md:flex items-center gap-1 flex-1">
        {[
          { to: '/dashboard', label: 'Dashboard' },
          { to: '/learn', label: 'Learn' },
          { to: '/doubts', label: 'Ask Doubt' },
          { to: '/progress', label: 'Progress' },
        ].map(({ to, label }) => (
          <Link
            key={to}
            to={to}
            className="px-3 py-1.5 text-sm text-paper/60 hover:text-paper hover:bg-surface-2 rounded-lg transition-colors"
          >
            {label}
          </Link>
        ))}
      </nav>

      {/* Right side */}
      <div className="flex items-center gap-3 ml-auto">
        {/* Streak */}
        <div className="flex items-center gap-1 bg-amber/10 border border-amber/20 rounded-lg px-2.5 py-1">
          <span className="text-sm">🔥</span>
          <span className="text-xs font-medium text-amber">{streak}</span>
        </div>
        {/* XP */}
        <div className="flex items-center gap-1 bg-violet/10 border border-violet/20 rounded-lg px-2.5 py-1">
          <span className="text-xs font-medium text-violet-light">{xp.toLocaleString()} XP</span>
        </div>
        {/* Avatar */}
        <button
          onClick={handleLogout}
          title="Logout"
          className="w-8 h-8 rounded-full bg-gradient-to-br from-violet to-indigo flex items-center justify-center text-white text-xs font-semibold hover:opacity-80 transition-opacity"
        >
          {name ? name[0].toUpperCase() : '?'}
        </button>
      </div>
    </header>
  )
}
