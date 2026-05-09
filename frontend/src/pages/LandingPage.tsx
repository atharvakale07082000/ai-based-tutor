import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import toast from 'react-hot-toast'
import { authAPI, setAccessToken } from '@/lib/api'
import { useLearnerStore } from '@/stores/learnerStore'
import { Button } from '@/components/ui/Button'

const prefersReducedMotion =
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

export default function LandingPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const navigate = useNavigate()
  const setLearner = useLearnerStore((s) => s.setLearner)

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    try {
      const { data } = await authAPI.login(email, password)
      setAccessToken(data.access_token)
      setLearner({ id: data.user.id, name: data.user.name, email: data.user.email })
      toast.success(`Welcome back, ${data.user.name}!`)
      navigate('/dashboard')
    } catch {
      toast.error('Invalid email or password')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-ink overflow-hidden relative flex">
      {/* Background mesh gradient */}
      <div
        className="absolute inset-0 opacity-40"
        style={{
          background: 'radial-gradient(at 40% 20%, #7C3AED33 0px, transparent 50%), radial-gradient(at 80% 0%, #4338CA33 0px, transparent 50%), radial-gradient(at 0% 50%, #4C1D9533 0px, transparent 50%)',
          backgroundSize: '200% 200%',
          animation: prefersReducedMotion ? 'none' : 'meshRotate 20s linear infinite',
        }}
      />

      {/* Floating orbs */}
      <div className="absolute w-96 h-96 rounded-full bg-violet/20 blur-[100px] top-[-10%] left-[10%] orb-1 pointer-events-none" />
      <div className="absolute w-80 h-80 rounded-full bg-indigo/20 blur-[100px] bottom-[10%] right-[15%] orb-2 pointer-events-none" />
      <div className="absolute w-64 h-64 rounded-full bg-violet-dim/30 blur-[80px] top-[60%] left-[40%] orb-3 pointer-events-none" />

      {/* LEFT PANEL — 55% */}
      <div className="relative z-10 flex flex-col justify-center px-12 lg:px-20 w-full lg:w-[55%]">
        {/* Eyebrow */}
        <motion.p
          initial={prefersReducedMotion ? {} : { opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="text-violet-light text-[11px] font-medium tracking-[0.25em] uppercase mb-6"
        >
          ADAPTIVE AI TUTORING PLATFORM
        </motion.p>

        {/* H1 */}
        <motion.h1
          initial={prefersReducedMotion ? {} : { opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="font-display text-5xl lg:text-[64px] leading-[1.1] text-paper mb-6"
        >
          Learn Smarter.
          <br />
          <span className="gradient-text">Not Harder.</span>
        </motion.h1>

        {/* Subheadline */}
        <motion.p
          initial={prefersReducedMotion ? {} : { opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="font-body text-lg text-paper/60 mb-10 max-w-lg"
        >
          Adaptive AI tutors that evolve with every lesson, quiz, and question you ask.
          Personalized education powered by four specialized agents working in concert.
        </motion.p>

        {/* Agent status strip */}
        <motion.div
          initial={prefersReducedMotion ? {} : { opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
          className="flex flex-wrap gap-2 mb-6"
        >
          {[
            { label: 'Curriculum Planner', color: 'emerald' },
            { label: 'Quiz Generator', color: 'emerald' },
            { label: 'Progress Tracker', color: 'emerald' },
            { label: 'Doubt-Solver', color: 'emerald' },
          ].map(({ label }) => (
            <span
              key={label}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-emerald/10 text-emerald border border-emerald/30 agent-pill-active"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-emerald" />
              {label} 🟢
            </span>
          ))}
        </motion.div>

      </div>

      {/* RIGHT PANEL — 45% */}
      <div className="hidden lg:flex items-center justify-center w-[45%] relative z-10 px-12">
        <motion.div
          initial={prefersReducedMotion ? {} : { opacity: 0, x: 40 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ type: 'spring', stiffness: 80, damping: 20, delay: 0.15 }}
          className="glass-strong rounded-3xl p-8 w-full max-w-md shadow-2xl shadow-black/50"
        >
          <h2 className="font-display text-2xl text-paper mb-2">Welcome back</h2>
          <p className="text-sm text-paper/50 mb-8">Sign in to your AI learning workspace</p>

          {/* Google SSO */}
          <button className="w-full flex items-center justify-center gap-3 bg-white text-gray-800 font-medium py-3 rounded-xl hover:bg-gray-100 transition-colors mb-4">
            <svg className="w-5 h-5" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg>
            Continue with Google
          </button>

          <div className="flex items-center gap-3 mb-4">
            <div className="h-px flex-1 bg-surface-3" />
            <span className="text-xs text-paper/30">or</span>
            <div className="h-px flex-1 bg-surface-3" />
          </div>

          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-xs text-paper/50 mb-1.5">Email address</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                required
                className="w-full bg-surface-2 border border-surface-3 rounded-xl px-4 py-3 text-sm text-paper placeholder-paper/30 focus:outline-none focus:ring-2 focus:ring-violet/50 focus:border-violet transition"
              />
            </div>
            <div>
              <label className="block text-xs text-paper/50 mb-1.5">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
                className="w-full bg-surface-2 border border-surface-3 rounded-xl px-4 py-3 text-sm text-paper placeholder-paper/30 focus:outline-none focus:ring-2 focus:ring-violet/50 focus:border-violet transition"
              />
            </div>
            <Button type="submit" variant="primary" size="lg" isLoading={isLoading} className="w-full">
              Sign in to AI Tutor
            </Button>
          </form>

          <p className="text-center text-xs text-paper/40 mt-6">
            New to AI Tutor?{' '}
            <a href="/onboarding" className="text-violet-light hover:underline">
              Create your learning profile →
            </a>
          </p>
        </motion.div>
      </div>

      {/* Mobile login form */}
      <div className="lg:hidden absolute bottom-0 left-0 right-0 p-6 glass border-t border-surface-2/50 z-20">
        <form onSubmit={handleLogin} className="flex flex-col gap-3">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email"
            className="bg-surface-2 border border-surface-3 rounded-xl px-4 py-3 text-sm text-paper placeholder-paper/30 focus:outline-none focus:ring-2 focus:ring-violet/50"
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            className="bg-surface-2 border border-surface-3 rounded-xl px-4 py-3 text-sm text-paper placeholder-paper/30 focus:outline-none focus:ring-2 focus:ring-violet/50"
          />
          <Button type="submit" isLoading={isLoading} className="w-full">Sign In</Button>
        </form>
      </div>
    </div>
  )
}
