import { Suspense, lazy, useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import { useLearnerStore } from '@/stores/learnerStore'
import { useThemeStore } from '@/stores/themeStore'
import { Sidebar } from '@/components/layout/Sidebar'
import { TopBar } from '@/components/layout/TopBar'
import { AgentStatusBar } from '@/components/agents/AgentStatusBar'
import { CommandPalette } from '@/components/layout/CommandPalette'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { PomodoroTimer } from '@/components/ui/PomodoroTimer'
import { useAgentSocket } from '@/hooks/useAgentSocket'

const LandingPage        = lazy(() => import('@/pages/LandingPage'))
const OnboardingPage     = lazy(() => import('@/pages/OnboardingPage'))
const DashboardPage      = lazy(() => import('@/pages/DashboardPage'))
const LearnFeedPage      = lazy(() => import('@/pages/LearnFeedPage'))
const ModulePlayerPage   = lazy(() => import('@/pages/ModulePlayerPage'))
const DoubtChatPage      = lazy(() => import('@/pages/DoubtChatPage'))
const QuizPage           = lazy(() => import('@/pages/QuizPage'))
const ProgressPage       = lazy(() => import('@/pages/ProgressPage'))
const AdminPage          = lazy(() => import('@/pages/AdminPage'))
const CoursePlannerPage  = lazy(() => import('@/pages/CoursePlannerPage'))
const CourseDetailPage   = lazy(() => import('@/pages/CourseDetailPage'))
const ModuleInterviewPage = lazy(() => import('@/pages/ModuleInterviewPage'))
const AssistantPage      = lazy(() => import('@/pages/AssistantPage'))
const AtelierV2Page      = lazy(() => import('@/pages/AtelierV2Page'))
const FlashcardsPage     = lazy(() => import('@/pages/FlashcardsPage'))
const ProfilePage        = lazy(() => import('@/pages/ProfilePage'))

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 1000 * 60 * 2, retry: 2 } },
})

function PageLoader() {
  return (
    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            background: 'var(--ink-0)',
            color: 'var(--paper-0)',
            display: 'grid',
            placeItems: 'center',
            fontFamily: 'var(--font-serif)',
            fontSize: 18,
            fontStyle: 'italic',
          }}
        >
          æ
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: 'var(--accent)',
                opacity: 0.6,
                animation: `blink 1.2s ease-in-out ${i * 0.2}s infinite`,
              }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const learnerId = useLearnerStore((s) => s.id)
  const [hydrated, setHydrated] = useState(useLearnerStore.persist.hasHydrated())

  useEffect(() => {
    if (hydrated) return
    const unsub = useLearnerStore.persist.onFinishHydration(() => setHydrated(true))
    setHydrated(useLearnerStore.persist.hasHydrated())
    return unsub
  }, [hydrated])

  if (!hydrated) return <PageLoader />
  if (!learnerId) return <Navigate to="/" replace />
  return <>{children}</>
}

// Pages that skip the shell entirely
const PUBLIC_ROUTES = ['/', '/onboarding', '/login']

function AppShell({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  const learnerId = useLearnerStore((s) => s.id ?? undefined)
  useAgentSocket({ learnerId })

  const isPublic = PUBLIC_ROUTES.includes(location.pathname)

  if (isPublic) {
    return (
      <div style={{ height: '100%', overflow: 'auto' }}>
        {children}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      <Sidebar />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <TopBar />
        <AgentStatusBar />
        <main style={{ flex: 1, overflowY: 'auto' }}>
          {children}
        </main>
      </div>
      <CommandPalette />
      <PomodoroTimer />
    </div>
  )
}

// Apply theme on initial load
function ThemeInitializer() {
  useThemeStore()
  return null
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ThemeInitializer />
        <Suspense fallback={
          <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--paper-0)' }}>
            <PageLoader />
          </div>
        }>
          <AppShell>
            <Routes>
              <Route path="/" element={<LandingPage />} />
              <Route path="/onboarding" element={<OnboardingPage />} />
              <Route path="/dashboard" element={<PrivateRoute><PageWrapper><DashboardPage /></PageWrapper></PrivateRoute>} />
              <Route path="/learn" element={<PrivateRoute><PageWrapper><LearnFeedPage /></PageWrapper></PrivateRoute>} />
              <Route path="/learn/:moduleId" element={<PrivateRoute><PageWrapper><ModulePlayerPage /></PageWrapper></PrivateRoute>} />
              <Route path="/doubts" element={<PrivateRoute><PageWrapper><DoubtChatPage /></PageWrapper></PrivateRoute>} />
              <Route path="/quiz/:quizId" element={<PrivateRoute><PageWrapper><QuizPage /></PageWrapper></PrivateRoute>} />
              <Route path="/progress" element={<PrivateRoute><PageWrapper><ProgressPage /></PageWrapper></PrivateRoute>} />
              <Route path="/admin/*" element={<PrivateRoute><PageWrapper><AdminPage /></PageWrapper></PrivateRoute>} />
              <Route path="/courses" element={<PrivateRoute><PageWrapper><CoursePlannerPage /></PageWrapper></PrivateRoute>} />
              <Route path="/courses/:planId" element={<PrivateRoute><PageWrapper><CourseDetailPage /></PageWrapper></PrivateRoute>} />
              <Route path="/courses/:planId/modules/:moduleId/interview" element={<PrivateRoute><PageWrapper><ModuleInterviewPage /></PageWrapper></PrivateRoute>} />
              <Route path="/assistant" element={<PrivateRoute><PageWrapper><AssistantPage /></PageWrapper></PrivateRoute>} />
              <Route path="/assistant-v2" element={<PrivateRoute><PageWrapper><AtelierV2Page /></PageWrapper></PrivateRoute>} />
              <Route path="/flashcards" element={<PrivateRoute><PageWrapper><FlashcardsPage /></PageWrapper></PrivateRoute>} />
              <Route path="/profile" element={<PrivateRoute><PageWrapper><ProfilePage /></PageWrapper></PrivateRoute>} />
              <Route path="/login" element={<Navigate to="/" replace />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </AppShell>
        </Suspense>

        <Toaster
          position="bottom-right"
          toastOptions={{
            style: {
              background: 'var(--paper-1)',
              color: 'var(--ink-0)',
              border: '1px solid var(--line-1)',
              borderRadius: 8,
              fontSize: 13,
              fontFamily: 'var(--font-sans)',
              boxShadow: 'var(--shadow-3)',
            },
            success: { iconTheme: { primary: 'var(--pos)', secondary: '#fff' } },
            error:   { iconTheme: { primary: 'var(--neg)', secondary: '#fff' } },
          }}
        />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
