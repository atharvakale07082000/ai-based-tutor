import { useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import InterviewRunner from '@/components/interview/InterviewRunner'
import { moduleEndpoints } from '@/components/interview/endpoints'
import { coursesAPI } from '@/lib/api'

/**
 * The AI interview for one course module.
 *
 * All of the interview machinery — voice, Monaco, resume, recovery, scoring — lives in
 * `InterviewRunner`, which the job-loop rounds share. This page's only job is to resolve
 * the module being interviewed on and point the runner at the course endpoints.
 */
export default function ModuleInterviewPage() {
  const { planId, moduleId } = useParams<{ planId: string; moduleId: string }>()

  const { data: plan } = useQuery({
    queryKey: ['course', planId],
    queryFn: () => coursesAPI.get(planId!).then((r) => r.data),
    enabled: !!planId,
    staleTime: 1000 * 60 * 5,
    gcTime: 1000 * 60 * 15,
  })

  const currentModule = plan?.modules.find((m) => m.id === moduleId)
  const endpoints = useMemo(
    () => moduleEndpoints(planId ?? '', moduleId ?? ''),
    [planId, moduleId],
  )

  return (
    <InterviewRunner
      endpoints={endpoints}
      subject={
        currentModule
          ? { title: currentModule.title, topics: currentModule.topics }
          : undefined
      }
    />
  )
}
