import axios from 'axios'
import toast from 'react-hot-toast'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

export const api = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true,
})

const TOKEN_KEY = 'ai_tutor_token'

let accessToken: string | null =
  typeof localStorage !== 'undefined' ? localStorage.getItem(TOKEN_KEY) : null

export function setAccessToken(token: string | null) {
  accessToken = token
  if (typeof localStorage !== 'undefined') {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token)
    } else {
      localStorage.removeItem(TOKEN_KEY)
    }
  }
}

export function getAccessToken() {
  return accessToken
}

// Attach Bearer token on every request
api.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  return config
})

// Auto-refresh on 401
api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true
      try {
        const { data } = await axios.post(`${BASE_URL}/auth/refresh`, {}, { withCredentials: true })
        setAccessToken(data.access_token)
        original.headers.Authorization = `Bearer ${data.access_token}`
        return api(original)
      } catch {
        setAccessToken(null)
        toast.error('Session expired. Please log in again.')
        window.location.href = '/onboarding'
      }
    }
    return Promise.reject(error)
  }
)

// ─── Auth ────────────────────────────────────────────────────────────────────

export interface LoginResponse {
  access_token: string
  refresh_token: string
  user: { id: string; email: string; name: string; role: string }
}

export const authAPI = {
  login: (email: string, password: string) =>
    api.post<LoginResponse>('/auth/login', { email, password }),
  refresh: () => api.post<{ access_token: string }>('/auth/refresh'),
  logout: () => api.post('/auth/logout'),
}

// ─── Learner ─────────────────────────────────────────────────────────────────

export interface LearnerProfileAPI {
  id: string
  user_id: string
  name: string
  goal_vector: string[]
  topic_proficiency_map: Record<string, number>
  learning_style: 'visual' | 'auditory' | 'reading' | 'kinesthetic'
  xp: number
  streak: number
  curriculum_version: number
}

export const learnerAPI = {
  getProfile: () => api.get<LearnerProfileAPI>('/learner/profile'),
  updateProfile: (data: Partial<LearnerProfileAPI>) => api.put<LearnerProfileAPI>('/learner/profile', data),
  onboard: (data: { name: string; goals: string[]; hoursPerWeek: number; difficulty: string }) =>
    api.post<{ name: string }>('/learner/onboard', data),
}

// ─── Curriculum ──────────────────────────────────────────────────────────────

export interface CurriculumItem {
  domain: string
  subtopic: string
  priority: number
}

export const curriculumAPI = {
  get: () => api.get<CurriculumItem[]>('/curriculum'),
  generate: () => api.post<{ items: CurriculumItem[] }>('/curriculum/generate'),
}

// ─── Content ─────────────────────────────────────────────────────────────────

export interface ContentItem {
  id: string
  title: string
  content_type: 'video' | 'article' | 'exercise' | 'interactive'
  topic: string
  subtopic?: string
  difficulty: number
  estimated_minutes: number
  body: string
  video_url?: string
  is_ai_recommended: boolean
}

export interface ContentListParams {
  topic?: string
  type?: string
  min_difficulty?: number
  max_difficulty?: number
  search?: string
  page?: number
  offset?: number
  limit?: number
}

export const contentAPI = {
  list: (params: ContentListParams = {}) =>
    api.get<{ items: ContentItem[]; total: number; has_more: boolean }>('/content', { params }),
  get: (id: string) => api.get<ContentItem>(`/content/${id}`),
  regenerate: (id: string) => api.post(`/content/${id}/regenerate`),
}

// ─── Quiz ─────────────────────────────────────────────────────────────────────

export interface QuizQuestion {
  id: string
  question: string
  options: string[]
  correct_index: number
  explanation: string
  bloom_level: string
}

export interface QuizSession {
  quiz_id: string
  topic: string
  bloom_level: string
  questions: QuizQuestion[]
  time_per_question: number
}

export interface QuizSubmitResult {
  score: number
  correct_count: number
  weak_topics: string[]
  elo_update: { topic: string; old_elo: number; new_elo: number }
}

export interface Flashcard {
  id: string
  front: string
  back: string
  hint: string
  difficulty: number
  topic: string
}

export const quizAPI = {
  generate: (topic: string, bloom_level?: string) =>
    api.post<QuizSession>('/quiz/generate', { topic, bloom_level }),
  get: (quizId: string) => api.get<QuizSession>(`/quiz/${quizId}`),
  submit: (quizId: string, answers: number[], reflection?: string) =>
    api.post<QuizSubmitResult>(`/quiz/${quizId}/submit`, { answers, reflection }),
  flashcards: (topic: string, count = 10) =>
    api.get<{ topic: string; cards: Flashcard[]; count: number }>('/quiz/flashcards', { params: { topic, count } }),
}

// ─── Doubts ───────────────────────────────────────────────────────────────────

export interface DoubtSessionSummary {
  id: string
  topic_context?: string
  sentiment_mood?: string
  started_at: string
  ended_at?: string
  message_count: number
}

export const doubtsAPI = {
  getSessions: () => api.get<DoubtSessionSummary[]>('/doubts/sessions'),
  getSession: (id: string) => api.get<{ id: string; messages: Array<{ role: string; content: string; timestamp: string }> }>(`/doubts/sessions/${id}`),
  transcribe: (audioBlob: Blob) => {
    const formData = new FormData()
    formData.append('audio', audioBlob, 'recording.webm')
    return api.post<{ transcript: string }>('/doubts/transcribe', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  caption: (imageBlob: Blob) => {
    const formData = new FormData()
    formData.append('image', imageBlob)
    return api.post<{ caption: string }>('/doubts/caption', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  streamUrl: () => `${BASE_URL}/doubts/stream`,
}

// ─── Progress ─────────────────────────────────────────────────────────────────

export interface ProgressData {
  learner_id: string
  topic_proficiency: Record<string, number>
  history: Array<{ topic: string; elo_score: number; recorded_at: string }>
  total_study_minutes: number
  quiz_accuracy: number
  doubts_resolved: number
  streak: number
  xp: number
  mood_timeline: Array<{ session_id: string; mood: string; date: string }>
}

export interface DueTopic {
  topic: string
  elo: number
  days_since_last_quiz: number | null
  is_due: boolean
  urgency: number
}

export const progressAPI = {
  get: () => api.get<ProgressData>('/progress'),
  downloadReport: () => api.get('/progress/report', { responseType: 'blob' }),
  dueTopics: () => api.get<{ due_topics: DueTopic[] }>('/progress/due-topics'),
  recordStudySession: (body: { minutes: number; topic?: string; activity?: string }) =>
    api.post<{ ok: boolean; xp_earned: number }>('/progress/study-session', body),
}

// ─── Leaderboard ──────────────────────────────────────────────────────────────

export interface LeaderboardEntry {
  rank: number
  name: string
  xp: number
  streak: number
  is_you: boolean
}

export interface LeaderboardResponse {
  board: LeaderboardEntry[]
  total_learners: number
  your_rank: number | null
  you: LeaderboardEntry | null
}

export const leaderboardAPI = {
  get: () => api.get<LeaderboardResponse>('/leaderboard'),
}

// ─── Curriculum graph ─────────────────────────────────────────────────────────

export const curriculumGraphAPI = {
  get: () =>
    api.get<{ nodes: Array<{ id: string; domain: string; elo: number | null; mastered: boolean; started: boolean }>; edges: Array<{ from: string; to: string }> }>('/curriculum/graph'),
}

// ─── HF ──────────────────────────────────────────────────────────────────────

export interface HFModelStatusAPI {
  status: 'ok' | 'error' | 'loading'
  last_used?: string
  latency_ms?: number
}

export const hfAPI = {
  status: () => api.get<Record<string, HFModelStatusAPI>>('/hf/status'),
  test: (modelKey: string) => api.post(`/hf/test/${modelKey}`),
}

// ─── Admin ────────────────────────────────────────────────────────────────────

export interface AdminLearner {
  id: string
  name: string
  email: string
  avg_proficiency: number
  last_active: string
  mood?: string
  topic_proficiency: Record<string, number>
}

export const adminAPI = {
  getLearners: (search = '', page = 1) =>
    api.get<{ items: AdminLearner[]; total: number }>('/admin/learners', { params: { search, page } }),
  updateConfig: (config: { quiz_frequency?: number; difficulty_ceiling?: number; escalation_threshold?: number }) =>
    api.put('/admin/config', config),
}

// ─── Courses ──────────────────────────────────────────────────────────────────

export interface CourseResource {
  title: string
  url: string
  type: 'video' | 'article' | 'course' | 'book' | 'tool'
}

export interface CourseModule {
  id: string
  title: string
  description: string
  topics: string[]
  duration_days: number
  resources: CourseResource[]
  order: number
  interview_status: 'pending' | 'in_progress' | 'passed' | 'failed'
  interview_score: number | null
}

export interface CoursePlan {
  plan_id: string
  user_id: string
  goal: string
  title: string
  description: string
  total_duration_weeks: number
  modules: CourseModule[]
  created_at: string
  status: string
}

export interface InterviewQuestion {
  id: number
  text: string
  expected_depth: string
}

export interface Interview {
  interview_id: string
  plan_id: string
  module_id: string
  module_title: string
  questions: InterviewQuestion[]
  answers: Array<{ question_id: number; score: number; feedback: string; answer_text: string }>
  final_score: number | null
  passed: boolean | null
  created_at: string
  completed_at: string | null
}

export const coursesAPI = {
  create: (goal: string) => api.post<CoursePlan>('/courses/plan', { goal }),
  list: () => api.get<CoursePlan[]>('/courses/'),
  get: (planId: string) => api.get<CoursePlan>(`/courses/${planId}`),
  startInterview: (planId: string, moduleId: string) =>
    api.post<Interview>(`/courses/${planId}/modules/${moduleId}/interview/start`),
  submitAnswer: (planId: string, moduleId: string, interviewId: string, questionId: number, answerText: string) =>
    api.post<{ question_id: number; score: number; feedback: string; answer_text: string; key_points_covered: string[] }>(
      `/courses/${planId}/modules/${moduleId}/interview/${interviewId}/answer`,
      { question_id: questionId, answer_text: answerText },
    ),
  completeInterview: (planId: string, moduleId: string, interviewId: string) =>
    api.post(`/courses/${planId}/modules/${moduleId}/interview/${interviewId}/complete`),
}

// ─── Feed ─────────────────────────────────────────────────────────────────────

export interface FeedItem {
  id: string
  title: string
  summary: string
  url: string
  source: string
  domain: string
  subtopic: string
  content_type: 'article' | 'video' | 'course' | 'news'
  is_trending: boolean
  is_ai_recommended: boolean
  estimated_minutes: number
  difficulty: number
  discovered_at: string
  expires_at: string
  _snoozed?: boolean
  _snoozed_until?: string | null
  _scheduled_for?: string | null
}

export interface TrendTopic {
  id: string
  domain: string
  subtopic: string
  description: string
  is_trending: boolean
  discovered_at: string
  _elo?: number | null
  _started?: boolean
}

export const feedAPI = {
  list: (params: { domain?: string; content_type?: string; page?: number; limit?: number } = {}) =>
    api.get<{ items: FeedItem[]; total: number; has_more: boolean; page: number }>('/feed', { params }),
  trending: (limit = 24) =>
    api.get<{ topics: TrendTopic[]; discovered_at: string; fresh: boolean }>('/feed/trending', { params: { limit } }),
  scheduled: () =>
    api.get<{ items: FeedItem[]; total: number }>('/feed/scheduled'),
  runDiscovery: () =>
    api.post('/feed/run-discovery'),
  snooze: (itemId: string, hours = 24) =>
    api.post(`/feed/${itemId}/snooze`, { hours }),
  schedule: (itemId: string, scheduledFor: string) =>
    api.post(`/feed/${itemId}/schedule`, { scheduled_for: scheduledFor }),
  clearInteraction: (itemId: string) =>
    api.delete(`/feed/${itemId}/interaction`),
}

// ─── Assistant ────────────────────────────────────────────────────────────────

export const assistantAPI = {
  streamChat: async (
    message: string,
    onChunk: (chunk: string) => void,
    onAction?: (kind: string, payload: Record<string, unknown>) => void,
    history?: Array<{ role: string; content: string }>,
  ): Promise<void> => {
    const response = await fetch(`${BASE_URL}/assistant/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: accessToken ? `Bearer ${accessToken}` : '',
      },
      body: JSON.stringify({ message, history: history ?? [] }),
    })
    if (!response.ok || !response.body) throw new Error('Stream failed')
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value, { stream: true })
        const lines = chunk.split('\n').filter((l) => l.startsWith('data: '))
        for (const line of lines) {
          const json = line.slice(6).trim()
          try {
            const event = JSON.parse(json)
            if (event.type === 'token' && event.content) onChunk(event.content)
            if (event.type === 'action' && onAction) onAction(event.kind, event.payload ?? {})
            if (event.type === 'done') return
          } catch { /* skip malformed SSE line */ }
        }
      }
    } catch (err) {
      reader.cancel().catch(() => {})
      throw new Error(err instanceof Error ? err.message : 'Stream read error')
    }
  },
}

// ─── Assistant V2 ─────────────────────────────────────────────────────────────

export type V2EventType = 'routing' | 'thought' | 'tool_call' | 'tool_result' | 'token' | 'action' | 'done' | 'error'

export interface V2RoutingEvent    { type: 'routing';     agent: string; reason: string }
export interface V2ThoughtEvent    { type: 'thought';     step: number;  content: string }
export interface V2ToolCallEvent   { type: 'tool_call';   step: number;  name: string; args: Record<string, unknown> }
export interface V2ToolResultEvent { type: 'tool_result'; step: number;  name: string; result: unknown; latency_ms: number }
export interface V2TokenEvent      { type: 'token';       content: string }
export interface V2ActionEvent     { type: 'action';      kind: string; payload: Record<string, unknown> }
export interface V2DoneEvent       { type: 'done';        steps: number; total_ms: number }
export interface V2ErrorEvent      { type: 'error';       message: string }

export type V2Event =
  | V2RoutingEvent
  | V2ThoughtEvent
  | V2ToolCallEvent
  | V2ToolResultEvent
  | V2TokenEvent
  | V2ActionEvent
  | V2DoneEvent
  | V2ErrorEvent

export const assistantV2API = {
  streamChat: async (
    message: string,
    onEvent: (event: V2Event) => void,
    history?: Array<{ role: string; content: string }>,
    context?: Record<string, unknown>,
  ): Promise<void> => {
    const response = await fetch(`${BASE_URL}/v2/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: accessToken ? `Bearer ${accessToken}` : '',
      },
      body: JSON.stringify({ message, history: history ?? [], context: context ?? {} }),
    })
    if (!response.ok || !response.body) throw new Error('V2 stream failed')
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value, { stream: true })
        const lines = chunk.split('\n').filter((l) => l.startsWith('data: '))
        for (const line of lines) {
          const json = line.slice(6).trim()
          if (json === '[DONE]') return
          try {
            const event = JSON.parse(json)
            if (event.type) onEvent(event)
          } catch { /* skip malformed */ }
        }
      }
    } catch (err) {
      reader.cancel().catch(() => {})
      throw new Error(err instanceof Error ? err.message : 'Stream read error')
    }
  },
}
