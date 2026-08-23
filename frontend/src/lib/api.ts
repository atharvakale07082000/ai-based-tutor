import type { QueryClient } from '@tanstack/react-query'
import axios from 'axios'
import toast from 'react-hot-toast'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

// ── Central auto-invalidation ─────────────────────────────────────────────────
// Call setQueryClientForInvalidation(queryClient) once at app root.
// After every successful mutating request (POST/PUT/PATCH/DELETE) the
// interceptor below fires invalidation based on the endpoint that was called.

let _qc: QueryClient | null = null

export function setQueryClientForInvalidation(qc: QueryClient) {
  _qc = qc
}

// URL pattern → query key arrays to invalidate.
// Checked in order; ALL matching entries fire (not just the first).
const INVALIDATION_MAP: Array<{ pattern: RegExp; keys: string[][] }> = [
  // Learner profile / onboarding
  { pattern: /\/learner\/onboard/, keys: [['learner'], ['curriculum'], ['progress']] },
  { pattern: /\/learner\/profile/, keys: [['learner'], ['progress']] },
  // Curriculum
  { pattern: /\/curriculum\/generate/, keys: [['curriculum']] },
  // Content
  { pattern: /\/content\/.*\/regenerate/, keys: [['content']] },
  // Quiz submission → affects progress + ELO
  { pattern: /\/quiz\/.*\/submit/, keys: [['progress'], ['learner'], ['leaderboard']] },
  // Course creation
  { pattern: /\/courses\/plan/, keys: [['courses']] },
  // Interview complete → unlock next module + update score
  { pattern: /\/interview\/.*\/complete/, keys: [['courses'], ['course'], ['progress']] },
  // Interview start → mark module in_progress
  { pattern: /\/interview\/start/, keys: [['course']] },
  // Loop creation → the tracker card gains a loop link
  { pattern: /\/loops\/stream/, keys: [['loops'], ['jobs']] },
  // Round graded / retried → the ladder, and the loop list, both move
  { pattern: /\/loops\/.*\/rounds\/.*\/(complete|retry|start)/, keys: [['loop'], ['loops']] },
  { pattern: /\/loops\/.*\/debrief/, keys: [['loop'], ['loops']] },
  // Study session recording (Pomodoro etc.)
  { pattern: /\/progress\/study-session/, keys: [['progress'], ['leaderboard'], ['learner']] },
  // Feed mutations
  { pattern: /\/feed\/run-discovery/, keys: [['feed'], ['trending']] },
  { pattern: /\/feed\/.*\/snooze/, keys: [['feed']] },
  { pattern: /\/feed\/.*\/schedule/, keys: [['feed'], ['scheduled']] },
  { pattern: /\/feed\/.*\/interaction/, keys: [['feed']] },
  // Activity logs (DELETE clear)
  { pattern: /\/profile\/activity-logs/, keys: [['activityLogs'], ['activityStats']] },
  // HF model test
  { pattern: /\/hf\/test\//, keys: [['hfStatus']] },
  // Admin config
  { pattern: /\/admin\/config/, keys: [['adminConfig']] },
]

const MUTATING_METHODS = new Set(['post', 'put', 'patch', 'delete'])

function _autoInvalidate(method: string, url: string) {
  if (!_qc || !MUTATING_METHODS.has(method.toLowerCase())) return
  for (const { pattern, keys } of INVALIDATION_MAP) {
    if (pattern.test(url)) {
      for (const key of keys) {
        _qc.invalidateQueries({ queryKey: key })
      }
    }
  }
}

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

// ── Deploy-version detection ─────────────────────────────────────────────────
// The backend stamps every response with X-App-Version (set via APP_VERSION env
// var, defaults to startup timestamp). When the version changes mid-session the
// backend was redeployed — we immediately clear auth and force a fresh login so
// users never hit stale sessions or broken API contracts.

const VERSION_KEY = 'ai_tutor_app_version'
let _seenVersion: string | null =
  typeof localStorage !== 'undefined' ? localStorage.getItem(VERSION_KEY) : null

function _onVersionChange(incoming: string) {
  if (_seenVersion && _seenVersion !== incoming) {
    // Redeployed — clear everything
    setAccessToken(null)
    if (typeof localStorage !== 'undefined') {
      localStorage.removeItem('ai-tutor-learner') // zustand persist store
      localStorage.removeItem(VERSION_KEY)
    }
    toast('The platform was just updated. Please log in again.', {
      icon: '🔄',
      duration: 5000,
    })
    setTimeout(() => { window.location.href = '/' }, 1800)
  }
  _seenVersion = incoming
  if (typeof localStorage !== 'undefined') localStorage.setItem(VERSION_KEY, incoming)
}

function _forceLogout() {
  setAccessToken(null)
  if (typeof localStorage !== 'undefined') {
    localStorage.removeItem('ai-tutor-learner')
    localStorage.removeItem(VERSION_KEY)
  }
  _qc?.clear()
  toast.error('Session expired. Please log in again.')
  window.location.href = '/'
}

// Auto-refresh on 401; version check + auto-invalidation on every success
// Backend guarantees 401 means only "token invalid/expired" — login wrong-password is 400.
api.interceptors.response.use(
  (res) => {
    const v = res.headers['x-app-version'] as string | undefined
    if (v) _onVersionChange(v)
    _autoInvalidate(res.config.method ?? '', res.config.url ?? '')
    return res
  },
  async (error) => {
    const original = error.config
    if (error.response?.status === 401) {
      if (!original._retry) {
        // First 401 — silently try to refresh the access token once
        original._retry = true
        try {
          const { data } = await axios.post(`${BASE_URL}/auth/refresh`, {}, { withCredentials: true })
          setAccessToken(data.access_token)
          original.headers.Authorization = `Bearer ${data.access_token}`
          return api(original)
        } catch {
          // Refresh also failed — session is dead
          _forceLogout()
          return Promise.reject(error)
        }
      }
      // Already retried — still 401, session is dead
      _forceLogout()
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

// Origin without the /api/v1 suffix — ops endpoints (/health) live at the root.
const ORIGIN = BASE_URL.replace(/\/api\/v1\/?$/, '')

export const systemAPI = {
  health: () => axios.get<{ status: string; agent: string; version: string }>(`${ORIGIN}/health`),
}

export const authAPI = {
  login: (email: string, password: string) =>
    api.post<LoginResponse>('/auth/login', { email, password }),
  refresh: () => api.post<{ access_token: string }>('/auth/refresh'),
  logout: () => api.post('/auth/logout'),
  resetRequest: (email: string) =>
    api.post<{ message: string }>('/auth/reset-request', { email }),
  resetConfirm: (token: string, new_password: string) =>
    api.post<{ message: string }>('/auth/reset-confirm', { token, new_password }),
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
  // Job-seeker fields
  target_role?: string
  current_role?: string
  years_of_experience?: number
  job_search_urgency?: 'actively_looking' | 'exploring' | 'not_yet'
  preferred_companies?: string[]
  job_readiness_score?: number
}

export interface OnboardPayload {
  name: string
  goals?: string[]
  hoursPerWeek?: number
  difficulty?: string
  target_role?: string
  current_role?: string
  years_of_experience?: number
  job_search_urgency?: string
  preferred_companies?: string[]
}

export const learnerAPI = {
  getProfile: () => api.get<LearnerProfileAPI>('/learner/profile'),
  updateProfile: (data: Partial<LearnerProfileAPI>) => api.put<LearnerProfileAPI>('/learner/profile', data),
  onboard: (data: OnboardPayload) => api.post<{ name: string }>('/learner/onboard', data),
  getRoles: () => api.get<{ roles: string[] }>('/learner/roles'),
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
  explain: (quizId: string, questionIndex: number) =>
    api.post<{ explanation: string }>(`/quiz/${quizId}/explain`, { question_index: questionIndex }),
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
  /** 0-100 from graded evidence only; null when nothing has been graded yet. */
  job_readiness: number | null
  /** The Elo at/above which a topic counts as mastered — served so clients never hardcode it. */
  mastery_elo: number
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
  sentiment: (text: string) => api.post<{ label: string; score: number }>('/hf/sentiment', { text }),
}

// ─── Evals (superuser-only) ────────────────────────────────────────────────────

export interface EvalMetricStat { eval_type: string; total: number; pass_rate: number; avg_score: number }
export interface EvalAgentStat { agent: string; total: number; pass_rate: number; avg_score: number }
export interface EvalRecentItem {
  eval_type: string
  agent: string
  score: number
  passed: boolean
  details?: { reason?: string; metric?: string }
  timestamp: string
}
export interface EvalDashboard {
  overall: { total: number; pass_rate: number; avg_score: number }
  by_metric: EvalMetricStat[]
  by_agent: EvalAgentStat[]
  recent: EvalRecentItem[]
  trend: Array<{ day: string; avg_score: number; count: number }>
}

export const evalsAPI = {
  dashboard: () => api.get<EvalDashboard>('/evals/dashboard'),
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

/** One row of the org-wide skill gap, aggregated server-side from real proficiency. */
export interface OrgSkillGap {
  name: string
  /** Share of learners tracking this topic who are below mastery, 0–1. */
  pct: number
  learners: number
  below_mastery: number
  avg_elo: number
}

export const adminAPI = {
  getLearners: (search = '', page = 1) =>
    api.get<{ items: AdminLearner[]; total: number }>('/admin/learners', { params: { search, page } }),
  getSkillGaps: () =>
    api.get<{ items: OrgSkillGap[]; mastery_elo: number }>('/admin/skill-gaps'),
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
  is_coding_question?: boolean
  language?: string | null
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

// The live module interview is driven turn-by-turn over SSE (see ModuleInterviewPage +
// backend agents/interview_agent.py). `start` and `answer` stream these typed events:
export type InterviewStreamEvent =
  | { type: 'interview_started'; interview_id: string; module_title: string }
  | { type: 'reasoning'; content: string }
  | { type: 'token'; content: string }
  | { type: 'question'; id: number; text: string; is_coding_question: boolean; language: string | null; expected_depth: string }
  | { type: 'evaluation'; question_id: number; score: number; feedback: string; key_points_covered: string[] }
  | { type: 'finished' }
  | { type: 'error'; message: string }

// ── Interview resume ─────────────────────────────────────────────────────────
// GET /courses/{plan_id}/modules/{module_id}/interview/{interview_id} — plain JSON
// (not SSE). Lets the UI rehydrate a live interview after a reload/navigation:
// which question is currently pending, and everything already graded.
//
// Mirrors course_planner.interview_state() — a deliberately whitelisted projection.
// Internal calibration state (candidate_proficiency Elo, current_interrupt_id) and the
// final grader's rationale (scoring_matrix/summary) are withheld server-side by design.

export interface InterviewAnsweredQuestion {
  question_id: number
  question_text: string
  answer_text: string
  /** null if the answer was recorded but never graded. */
  score: number | null
  feedback: string
  key_points_covered: string[]
}

export interface InterviewState {
  interview_id: string
  plan_id: string
  module_id: string
  module_title: string
  /**
   * What the client should do next:
   * - `awaiting_answer` — agent paused on `current_question`; POST an answer.
   * - `awaiting_final`  — agent concluded; POST `.../complete` to grade it.
   * - `complete`        — already graded (`final_score`/`passed` are set).
   * - `in_progress`     — nothing outstanding, not concluded (interrupted start).
   */
  status: 'awaiting_answer' | 'awaiting_final' | 'complete' | 'in_progress'
  /** Non-null exactly when `status === 'awaiting_answer'`. */
  current_question: InterviewQuestion | null
  /** Questions already answered, chronological, each with its grade. */
  answers: InterviewAnsweredQuestion[]
  answered_count: number
  questions_asked: number
  max_questions: number
  final_score: number | null
  passed: boolean | null
  created_at: string
  completed_at: string | null
}

export const coursesAPI = {
  create: (goal: string) => api.post<CoursePlan>('/courses/plan', { goal }),
  list: () => api.get<CoursePlan[]>('/courses/'),
  get: (planId: string) => api.get<CoursePlan>(`/courses/${planId}`),
  /** Rehydrate an in-progress module interview (plain JSON; `start`/`answer` are SSE). */
  getInterview: (planId: string, moduleId: string, interviewId: string) =>
    api.get<InterviewState>(`/courses/${planId}/modules/${moduleId}/interview/${interviewId}`),
  completeInterview: (planId: string, moduleId: string, interviewId: string) =>
    api.post(`/courses/${planId}/modules/${moduleId}/interview/${interviewId}/complete`),
  runCode: (planId: string, moduleId: string, interviewId: string, code: string, language = 'python') =>
    api.post<{ stdout: string; stderr: string; exit_code: number }>(
      `/courses/${planId}/modules/${moduleId}/interview/${interviewId}/run-code`,
      { code, language },
    ),
}

// ─── Interview loops ──────────────────────────────────────────────────────────
// A saved job application spawns a loop: the rounds that employer probably runs, each
// graded against a bar calibrated to the JD's seniority (backend agents/bar.py). Rounds
// are conducted by the same interview machinery as module interviews — see
// components/interview/endpoints.ts for the per-round URLs.

export type RoundKind = 'screen' | 'coding' | 'system_design' | 'behavioral'
export type RoundStatus = 'locked' | 'available' | 'in_progress' | 'passed' | 'failed'
export type LoopStatus = 'in_progress' | 'passed' | 'failed'

export interface InterviewRound {
  key: string
  title: string
  kind: RoundKind
  order: number
  focus_skills: string[]
  /** Score out of 10 this round must reach to pass. */
  bar: number
  status: RoundStatus
  score: number | null
  attempt: number
  interview_id: string | null
  max_questions: number
}

export interface LoopDebrief {
  verdict: string
  strengths: string[]
  gaps: string[]
  focus_next: string
  rounds_cleared: number
  rounds_total: number
}

export interface InterviewLoop {
  loop_id: string
  job_id: string
  company: string
  role: string
  seniority: string
  target_skills: string[]
  /** Vetted prose summary of the company's process; the raw scraped text is never sent. */
  process_summary: string
  status: LoopStatus
  rounds: InterviewRound[]
  debrief: LoopDebrief | null
  created_at: string
  completed_at: string | null
}

export const loopsAPI = {
  list: () => api.get<{ loops: InterviewLoop[] }>('/loops'),
  get: (loopId: string) => api.get<InterviewLoop>(`/loops/${loopId}`),
  /** Reset a graded round for another attempt; returns the updated loop. */
  retryRound: (loopId: string, roundKey: string) =>
    api.post<InterviewLoop>(`/loops/${loopId}/rounds/${roundKey}/retry`),
}

// ─── Job Tracker ──────────────────────────────────────────────────────────────

export type JobStage = 'saved' | 'applied' | 'interview' | 'offer' | 'rejected'

export interface SkillGap {
  skill: string
  have_elo: number | null
  status: 'have' | 'partial' | 'missing'
}

export interface JobRecommendation {
  type: 'quiz' | 'course'
  skill: string
  label: string
  url: string
}

export interface JobApplication {
  id: string
  learner_id: string
  company: string
  role: string
  seniority: string
  required_skills: string[]
  stage: JobStage
  source_jd: string
  readiness_score: number
  skill_gaps: SkillGap[]
  recommendations: JobRecommendation[]
  notes: string
  created_at: string
  updated_at: string
  /** Set once this application has spawned an interview loop. */
  loop_id?: string | null
}

// Payload of the `jd_analyzed` action streamed by /jobs/analyze/stream.
export interface JDAnalysis {
  company: string
  role: string
  seniority: string
  required_skills: string[]
  readiness_score: number
  skill_gaps: SkillGap[]
  recommendations: JobRecommendation[]
  source_jd: string
}

export const jobsAPI = {
  list: () => api.get<{ jobs: JobApplication[] }>('/jobs'),
  get: (id: string) => api.get<JobApplication>(`/jobs/${id}`),
  create: (job: Partial<JobApplication>) => api.post<JobApplication>('/jobs', job),
  update: (id: string, patch: Partial<Pick<JobApplication, 'company' | 'role' | 'seniority' | 'stage' | 'notes'>>) =>
    api.patch<JobApplication>(`/jobs/${id}`, patch),
  remove: (id: string) => api.delete(`/jobs/${id}`),
  // analyze + reanalyze stream via streamSSE('/jobs/analyze/stream' | `/jobs/${id}/reanalyze/stream`)
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

// ─── Activity Logs ────────────────────────────────────────────────────────────

export interface ActivityLogEntry {
  id: string
  user_id: string
  action: string
  method: string
  endpoint: string
  ip_address?: string | null
  user_agent?: string | null
  status_code: number
  duration_ms: number
  metadata?: Record<string, unknown>
  timestamp: string
}

export interface ActivityLogsResponse {
  logs: ActivityLogEntry[]
  total: number
}

export interface ActivityStats {
  action_counts: Record<string, number>
  most_active_day: string | null
  total_actions: number
  window_days: number
}

export const activityAPI = {
  getLogs: (params: { limit?: number; skip?: number; action_filter?: string } = {}) =>
    api.get<ActivityLogsResponse>('/profile/activity-logs', { params }),
  getStats: () => api.get<ActivityStats>('/profile/activity-stats'),
  clearLogs: () => api.delete<{ deleted: boolean; count: number; message: string }>('/profile/activity-logs'),
}

// ─── Assistant V2 ─────────────────────────────────────────────────────────────

export type V2EventType = 'routing' | 'reasoning' | 'token' | 'action' | 'done' | 'error'

export interface V2RoutingEvent   { type: 'routing';   agent: string; reason: string }
export interface V2ReasoningEvent { type: 'reasoning'; content: string }
export interface V2TokenEvent     { type: 'token';     content: string }
export interface V2ActionEvent    { type: 'action';    kind: string; payload: Record<string, unknown> }
export interface V2DoneEvent      { type: 'done';      steps: number; total_ms: number }
export interface V2ErrorEvent     { type: 'error';     message: string }

export interface StepEvent { type: 'step'; id: string; label: string; status: 'active' | 'done' | 'error' }

export type V2Event =
  | V2RoutingEvent
  | V2ReasoningEvent
  | V2TokenEvent
  | V2ActionEvent
  | V2DoneEvent
  | V2ErrorEvent
  | StepEvent

// ─── Stream cancellation ──────────────────────────────────────────────────────
// Both streaming helpers below accept `{ signal }`. Aborting is a normal user
// action ("Stop"), never a failure: the helper resolves quietly instead of
// throwing, so callers need no special-casing and no error toast fires.

export interface StreamOptions {
  /** Abort the in-flight stream. On abort the promise resolves quietly (no throw). */
  signal?: AbortSignal
}

/** True for the `AbortError` DOMException browsers raise when a fetch/reader is aborted. */
export function isAbortError(err: unknown): boolean {
  return typeof err === 'object' && err !== null && (err as { name?: string }).name === 'AbortError'
}

// Single chat endpoint: /api/v1/chat (BASE_URL already includes /api/v1).
export const chatAPI = {
  streamChat: async (
    message: string,
    onEvent: (event: V2Event) => void,
    history?: Array<{ role: string; content: string }>,
    context?: Record<string, unknown>,
    /** Stable chat-thread id → enables persistent per-thread memory server-side. */
    sessionId?: string,
    options?: StreamOptions,
  ): Promise<void> => {
    const signal = options?.signal
    if (signal?.aborted) return
    let response: Response
    try {
      response = await fetch(`${BASE_URL}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: accessToken ? `Bearer ${accessToken}` : '',
          ...(sessionId ? { 'X-Session-Id': sessionId } : {}),
        },
        body: JSON.stringify({ message, history: history ?? [], context: context ?? {} }),
        signal,
      })
    } catch (err) {
      if (isAbortError(err) || signal?.aborted) return
      throw err
    }
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
      if (isAbortError(err) || signal?.aborted) return // user pressed Stop — not an error
      throw new Error(err instanceof Error ? err.message : 'Stream read error')
    } finally {
      // Aborting mid-stream leaves the body locked; releasing is a no-op if already done.
      if (signal?.aborted) reader.cancel().catch(() => {})
    }
  },
}

// ─── Generic agent step streaming ─────────────────────────────────────────────
// Reusable SSE driver for any endpoint that streams typed JSON events terminated
// by the `[DONE]` sentinel (course generation, quiz review, interview review, …).
// Buffers partial frames so events split across network reads parse correctly.

export async function streamSSE(
  path: string,
  body: unknown,
  onEvent: (event: { type: string } & Record<string, unknown>) => void,
  options?: StreamOptions,
): Promise<void> {
  const signal = options?.signal
  // Already cancelled before we even hit the network — nothing to do.
  if (signal?.aborted) return
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: accessToken ? `Bearer ${accessToken}` : '',
      },
      body: JSON.stringify(body ?? {}),
      signal,
    })
  } catch (err) {
    if (isAbortError(err) || signal?.aborted) return
    throw err
  }
  if (!response.ok || !response.body) throw new Error(`Stream failed: ${response.status}`)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? '' // keep the last, possibly-partial line for the next read
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const json = line.slice(6).trim()
        if (!json) continue
        if (json === '[DONE]') return
        try {
          const event = JSON.parse(json)
          if (event && event.type) onEvent(event)
        } catch { /* skip malformed frame */ }
      }
    }
  } catch (err) {
    reader.cancel().catch(() => {})
    if (isAbortError(err) || signal?.aborted) return // user pressed Stop — not an error
    throw new Error(err instanceof Error ? err.message : 'Stream read error')
  } finally {
    // Aborting mid-stream leaves the body locked; releasing is a no-op if already done.
    if (signal?.aborted) reader.cancel().catch(() => {})
  }
}
