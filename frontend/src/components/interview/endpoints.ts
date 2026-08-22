// Where an interview's turns live on the API.
//
// Two flows drive the same interview machinery — a course module interview and one round
// of a job interview loop — over identically-shaped SSE endpoints on identically-shaped
// documents (see backend `course_planner.start_interview`). This descriptor is the only
// thing that differs between them, so `InterviewRunner` takes one instead of knowing
// which flow it is running.

export interface InterviewEndpoints {
  /** localStorage key holding the in-flight interview id, so a reloaded tab can resume. */
  storageKey: string
  /** POST, SSE — opens the interview and streams the first question. */
  start: string
  /** POST, SSE — grades an answer and streams the next question (or `finished`). */
  answer: (interviewId: string) => string
  /** POST, SSE — final scoring. */
  complete: (interviewId: string) => string
  /** GET, plain JSON — rehydrate an interview after a reload. */
  resume: (interviewId: string) => string
  /** POST — check code from a coding question. */
  runCode: (interviewId: string) => string
  /** Where the "Back" affordances navigate to when the learner leaves. */
  backHref: string
  backLabel: string
}

export const moduleEndpoints = (planId: string, moduleId: string): InterviewEndpoints => {
  const base = `/courses/${planId}/modules/${moduleId}/interview`
  return {
    storageKey: `atelier.interview.${planId}.${moduleId}`,
    start: `${base}/start`,
    answer: (id) => `${base}/${id}/answer`,
    complete: (id) => `${base}/${id}/complete/stream`,
    resume: (id) => `${base}/${id}`,
    runCode: (id) => `${base}/${id}/run-code`,
    backHref: `/courses/${planId}`,
    backLabel: 'Back to Plan',
  }
}

// Loop rounds are addressed by round key rather than interview id — the server already
// knows which interview backs the round — so these ignore the id they're handed.
export const loopRoundEndpoints = (loopId: string, roundKey: string): InterviewEndpoints => {
  const base = `/loops/${loopId}/rounds/${roundKey}`
  return {
    storageKey: `atelier.loop.${loopId}.${roundKey}`,
    start: `${base}/start`,
    answer: () => `${base}/answer`,
    complete: () => `${base}/complete/stream`,
    resume: () => base,
    runCode: () => `${base}/run-code`,
    backHref: `/loops/${loopId}`,
    backLabel: 'Back to Loop',
  }
}
