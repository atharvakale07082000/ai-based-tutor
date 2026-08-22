import { useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import InterviewRunner from '@/components/interview/InterviewRunner'
import { loopRoundEndpoints } from '@/components/interview/endpoints'
import { loopsAPI } from '@/lib/api'

/**
 * One round of a company-specific interview loop.
 *
 * Same runner as the module interview — only the endpoints, the subject and the bar
 * differ. Resolving the round from the loop here keeps the runner unaware of which
 * flow it is serving.
 */
export default function LoopRoundPage() {
  const { loopId, roundKey } = useParams<{ loopId: string; roundKey: string }>()

  const { data: loop } = useQuery({
    queryKey: ['loop', loopId],
    queryFn: () => loopsAPI.get(loopId!).then((r) => r.data),
    enabled: !!loopId,
    staleTime: 1000 * 60,
  })

  const round = loop?.rounds.find((r) => r.key === roundKey)
  const endpoints = useMemo(
    () => loopRoundEndpoints(loopId ?? '', roundKey ?? ''),
    [loopId, roundKey],
  )

  return (
    <InterviewRunner
      endpoints={endpoints}
      bar={round?.bar}
      maxQuestions={round?.max_questions}
      knownInterviewId={round?.interview_id}
      subject={
        round && loop
          ? {
              title: round.title,
              topics: round.focus_skills,
              blurb: `${loop.role} at ${loop.company}`,
            }
          : undefined
      }
    />
  )
}
