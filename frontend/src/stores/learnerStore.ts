import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface QuizSessionHistory {
  id: string
  topic: string
  score: number
  bloom_level: string
  completed_at: string
}

export interface DoubtSessionHistory {
  id: string
  topic_context?: string
  sentiment_mood?: string
  started_at: string
  message_count: number
}

interface LearnerState {
  id: string | null
  name: string
  email: string
  xp: number
  streak: number
  goalVector: string[]
  topicProficiency: Record<string, number>
  learningStyle: 'visual' | 'auditory' | 'reading' | 'kinesthetic'
  quizHistory: QuizSessionHistory[]
  doubtSessions: DoubtSessionHistory[]
  curriculumVersion: number
  totalStudyMinutes: number
  quizAccuracy: number
  doubtsResolved: number
  moodTimeline: Array<{ session_id: string; mood: string; date: string }>

  setLearner: (data: Partial<LearnerState>) => void
  updateProficiency: (topic: string, score: number) => void
  addQuizSession: (session: QuizSessionHistory) => void
  addDoubtSession: (session: DoubtSessionHistory) => void
  reset: () => void
}

const initialState = {
  id: null,
  name: '',
  email: '',
  xp: 0,
  streak: 0,
  goalVector: [],
  topicProficiency: {},
  learningStyle: 'visual' as const,
  quizHistory: [],
  doubtSessions: [],
  curriculumVersion: 1,
  totalStudyMinutes: 0,
  quizAccuracy: 0,
  doubtsResolved: 0,
  moodTimeline: [],
}

export const useLearnerStore = create<LearnerState>()(
  persist(
    (set) => ({
      ...initialState,

      setLearner: (data) => set((state) => ({ ...state, ...data })),

      updateProficiency: (topic, score) =>
        set((state) => ({
          topicProficiency: { ...state.topicProficiency, [topic]: Math.max(0, Math.min(1000, score)) },
        })),

      addQuizSession: (session) =>
        set((state) => ({ quizHistory: [session, ...state.quizHistory].slice(0, 50) })),

      addDoubtSession: (session) =>
        set((state) => ({ doubtSessions: [session, ...state.doubtSessions].slice(0, 20) })),

      reset: () => {
        if (typeof localStorage !== 'undefined') localStorage.removeItem('ai_tutor_token')
        set(initialState)
      },
    }),
    {
      name: 'ai-tutor-learner',
      partialize: (state) => ({
        id: state.id,
        name: state.name,
        email: state.email,
        goalVector: state.goalVector,
        learningStyle: state.learningStyle,
        topicProficiency: state.topicProficiency,
        xp: state.xp,
        streak: state.streak,
      }),
    }
  )
)
