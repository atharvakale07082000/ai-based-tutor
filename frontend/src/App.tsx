import { Suspense, lazy, useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AnimatePresence } from 'framer-motion'
import { Toaster } from 'react-hot-toast'
import { useLearnerStore } from '@/stores/learnerStore'

// Route-based code splitting (lazy load every page)
const LandingPage = lazy(() => import('@/pages/LandingPage'))
const OnboardingPage = lazy(() => import('@/pages/OnboardingPage'))
const DashboardPage = lazy(() => import('@/pages/DashboardPage'))
const LearnFeedPage = lazy(() => import('@/pages/LearnFeedPage'))
const ModulePlayerPage = lazy(() => import('@/pages/ModulePlayerPage'))
const DoubtChatPage = lazy(() => import('@/pages/DoubtChatPage'))
const QuizPage = lazy(() => import('@/pages/QuizPage'))
const ProgressPage = lazy(() => import('@/pages/ProgressPage'))
const AdminPage = lazy(() => import('@/pages/AdminPage'))
const CoursePlannerPage = lazy(() => import('@/pages/CoursePlannerPage'))
const CourseDetailPage = lazy(() => import('@/pages/CourseDetailPage'))
const ModuleInterviewPage = lazy(() => import('@/pages/ModuleInterviewPage'))
const AssistantPage = lazy(() => import('@/pages/AssistantPage'))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 2,
      retry: 2,
    },
  },
})

function PageLoader() {
  return (
    <div className="min-h-screen bg-ink flex items-center justify-center">
      <div className="flex flex-col items-center gap-4">
        <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-violet to-indigo flex items-center justify-center text-white text-lg font-bold animate-pulse">
          AI
        </div>
        <div className="flex gap-1.5">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="w-1.5 h-1.5 rounded-full bg-violet/60"
              style={{ animation: `blink 1.2s ease-in-out ${i * 0.2}s infinite` }}
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

function OfflineBanner() {
  if (typeof window !== 'undefined' && !navigator.onLine) {
    return (
      <div className="fixed top-0 left-0 right-0 z-[100] bg-rose/90 text-white text-sm text-center py-2">
        No internet connection — some features may be unavailable
      </div>
    )
  }
  return null
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <OfflineBanner />
        <Suspense fallback={<PageLoader />}>
          <AnimatePresence mode="wait">
            <Routes>
              <Route path="/" element={<LandingPage />} />
              <Route path="/onboarding" element={<OnboardingPage />} />
              <Route path="/dashboard" element={<PrivateRoute><DashboardPage /></PrivateRoute>} />
              <Route path="/learn" element={<PrivateRoute><LearnFeedPage /></PrivateRoute>} />
              <Route path="/learn/:moduleId" element={<PrivateRoute><ModulePlayerPage /></PrivateRoute>} />
              <Route path="/doubts" element={<PrivateRoute><DoubtChatPage /></PrivateRoute>} />
              <Route path="/quiz/:quizId" element={<PrivateRoute><QuizPage /></PrivateRoute>} />
              <Route path="/progress" element={<PrivateRoute><ProgressPage /></PrivateRoute>} />
              <Route path="/admin/*" element={<PrivateRoute><AdminPage /></PrivateRoute>} />
              <Route path="/courses" element={<PrivateRoute><CoursePlannerPage /></PrivateRoute>} />
              <Route path="/courses/:planId" element={<PrivateRoute><CourseDetailPage /></PrivateRoute>} />
              <Route path="/courses/:planId/modules/:moduleId/interview" element={<PrivateRoute><ModuleInterviewPage /></PrivateRoute>} />
              <Route path="/assistant" element={<PrivateRoute><AssistantPage /></PrivateRoute>} />
              <Route path="/login" element={<Navigate to="/" replace />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </AnimatePresence>
        </Suspense>
      </BrowserRouter>

      <Toaster
        position="bottom-right"
        toastOptions={{
          style: {
            background: '#1F2937',
            color: '#F9FAFB',
            border: '1px solid #374151',
            borderRadius: '12px',
            fontSize: '14px',
          },
          success: { iconTheme: { primary: '#10B981', secondary: '#fff' } },
          error: { iconTheme: { primary: '#F43F5E', secondary: '#fff' } },
        }}
      />
    </QueryClientProvider>
  )
}
