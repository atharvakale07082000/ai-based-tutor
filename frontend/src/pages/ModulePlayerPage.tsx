import { useState, useRef } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import { contentAPI, quizAPI } from '@/lib/api'
import { runImageCaption } from '@/lib/hf'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Skeleton'
import toast from 'react-hot-toast'

export default function ModulePlayerPage() {
  const { moduleId } = useParams<{ moduleId: string }>()
  const navigate = useNavigate()
  const [progress, setProgress] = useState(0)
  const [showQuizPrompt, setShowQuizPrompt] = useState(false)
  const [doubtInput, setDoubtInput] = useState('')
  const [captionLoading, setCaptionLoading] = useState(false)
  const dropRef = useRef<HTMLDivElement>(null)

  const { data: module, isLoading } = useQuery({
    queryKey: ['content', 'module', moduleId],
    queryFn: () => contentAPI.get(moduleId!).then((r) => r.data),
    enabled: !!moduleId,
  })

  const handleImageDrop = async (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (!file || !file.type.startsWith('image/')) return
    setCaptionLoading(true)
    try {
      const caption = await runImageCaption(file)
      setDoubtInput((prev) => `[Image: ${caption}]\n${prev}`)
      toast.success('Image captioned')
    } catch {
      toast.error('Could not caption image')
    } finally {
      setCaptionLoading(false)
    }
  }

  const handleMarkComplete = async () => {
    setProgress(100)
    setShowQuizPrompt(true)
  }

  const handleStartQuiz = async () => {
    if (!module) return
    try {
      const { data } = await quizAPI.generate(module.topic)
      navigate(`/quiz/${data.quiz_id}`)
    } catch {
      toast.error('Could not generate quiz')
    }
  }

  return (
    <PageWrapper>
      {/* Breadcrumb */}
      <div className="px-6 py-3 border-b border-surface-2/50 flex items-center gap-2 text-sm text-paper/40">
        <Link to="/dashboard" className="hover:text-paper transition-colors">Home</Link>
        <span>›</span>
        <Link to="/learn" className="hover:text-paper transition-colors">Learn</Link>
        <span>›</span>
        <span className="text-paper/70">{module?.topic ?? '…'}</span>
        <span>›</span>
        <span className="text-paper/70 truncate max-w-[200px]">{module?.title ?? '…'}</span>
      </div>

      <div className="flex flex-col lg:flex-row h-[calc(100vh-8rem)] overflow-hidden">
        {/* LEFT 70%: Content area */}
        <div className="flex-1 lg:w-[70%] overflow-y-auto px-6 py-8">
          {isLoading ? (
            <div className="space-y-4">
              <Skeleton className="h-8 w-2/3" />
              <Skeleton lines={8} />
            </div>
          ) : module ? (
            <>
              <div className="flex items-center gap-3 mb-4">
                <Badge variant={module.content_type === 'video' ? 'violet' : 'indigo'}>
                  {module.content_type}
                </Badge>
                <Badge variant="surface">⏱ {module.estimated_minutes}m</Badge>
                <Badge variant="surface">{module.topic}</Badge>
              </div>
              <h1 className="font-display text-3xl text-paper mb-6">{module.title}</h1>

              {/* Video player */}
              {module.content_type === 'video' && module.video_url && (
                <div className="aspect-video bg-surface-1 rounded-2xl overflow-hidden mb-8 border border-surface-2">
                  <video
                    src={module.video_url}
                    controls
                    className="w-full h-full"
                    onTimeUpdate={(e) => {
                      const el = e.currentTarget
                      setProgress((el.currentTime / el.duration) * 100)
                      if (el.currentTime >= el.duration * 0.9) setShowQuizPrompt(true)
                    }}
                  />
                </div>
              )}

              {/* Markdown renderer */}
              <div className="prose-ai max-w-none text-paper/80 leading-relaxed">
                <ReactMarkdown>{module.body}</ReactMarkdown>
              </div>

              {/* Image drop zone */}
              <div
                ref={dropRef}
                onDragOver={(e) => e.preventDefault()}
                onDrop={handleImageDrop}
                className="mt-10 border-2 border-dashed border-surface-3 hover:border-violet/50 rounded-2xl p-8 text-center transition-colors cursor-pointer"
              >
                {captionLoading ? (
                  <div className="flex flex-col items-center gap-2 text-violet-light">
                    <svg className="w-8 h-8 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
                    </svg>
                    <span className="text-sm">Captioning image…</span>
                  </div>
                ) : (
                  <>
                    <div className="text-3xl mb-2">🖼️</div>
                    <p className="text-sm text-paper/50">Drop an image here to caption it and add to your doubt</p>
                  </>
                )}
              </div>

              {/* Doubt input */}
              {doubtInput && (
                <div className="mt-4">
                  <label className="text-xs text-paper/50 mb-1.5 block">Your doubt (pre-filled from image caption)</label>
                  <textarea
                    value={doubtInput}
                    onChange={(e) => setDoubtInput(e.target.value)}
                    className="w-full bg-surface-2 border border-surface-3 rounded-xl px-4 py-3 text-sm text-paper focus:outline-none focus:ring-2 focus:ring-violet/50 resize-none h-24"
                  />
                  <Button
                    size="sm"
                    className="mt-2"
                    onClick={() => navigate('/doubts', { state: { prefill: doubtInput, topic: module.topic } })}
                  >
                    Ask Doubt-Solver →
                  </Button>
                </div>
              )}

              <div className="mt-8">
                <Button onClick={handleMarkComplete} variant="secondary">
                  Mark as Complete ✓
                </Button>
              </div>
            </>
          ) : null}
        </div>

        {/* RIGHT 30%: Sticky panel */}
        <div className="hidden lg:flex lg:w-[30%] border-l border-surface-2/50 flex-col">
          <div className="p-6 overflow-y-auto flex-1">
            {/* Progress */}
            <div className="mb-6">
              <div className="flex justify-between text-xs text-paper/50 mb-2">
                <span>Module progress</span>
                <span>{Math.round(progress)}%</span>
              </div>
              <div className="h-2 bg-surface-2 rounded-full overflow-hidden">
                <motion.div
                  className="h-full bg-gradient-to-r from-violet to-indigo-light rounded-full"
                  animate={{ width: `${progress}%` }}
                  transition={{ duration: 0.5 }}
                />
              </div>
            </div>

            {/* Table of contents */}
            <div className="mb-6">
              <h3 className="text-xs font-medium text-paper/50 uppercase tracking-wider mb-3">Contents</h3>
              <div className="space-y-1">
                {['Introduction', 'Core Concepts', 'Examples', 'Practice', 'Summary'].map((section) => (
                  <button key={section} className="w-full text-left text-sm text-paper/60 hover:text-paper px-3 py-2 rounded-lg hover:bg-surface-2 transition-colors">
                    {section}
                  </button>
                ))}
              </div>
            </div>

            {/* Ask doubt bubble */}
            <div className="bg-violet/10 border border-violet/20 rounded-2xl p-4">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xl">💡</span>
                <span className="text-sm font-medium text-paper">Got a doubt?</span>
              </div>
              <p className="text-xs text-paper/50 mb-3">
                Ask the Doubt-Solver AI agent
              </p>
              <Button
                size="sm"
                variant="outline"
                className="w-full"
                onClick={() => navigate('/doubts', { state: { topic: module?.topic } })}
              >
                Open Doubt Chat
              </Button>
            </div>
          </div>
        </div>
      </div>

      {/* Quiz prompt slides up */}
      <AnimatePresence>
        {showQuizPrompt && (
          <motion.div
            initial={{ y: 100, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 100, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 80, damping: 20 }}
            className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 glass-strong rounded-2xl p-6 shadow-2xl border border-violet/30 max-w-md w-full mx-4"
          >
            <div className="flex items-start gap-4">
              <span className="text-3xl">🎉</span>
              <div className="flex-1">
                <h3 className="font-medium text-paper mb-1">Module complete!</h3>
                <p className="text-sm text-paper/60 mb-4">Ready to test your knowledge with a quiz?</p>
                <div className="flex gap-3">
                  <Button size="sm" onClick={handleStartQuiz}>Take Quiz</Button>
                  <Button size="sm" variant="ghost" onClick={() => setShowQuizPrompt(false)}>Later</Button>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </PageWrapper>
  )
}
