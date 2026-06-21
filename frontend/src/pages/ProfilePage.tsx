import { useState, useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { useLearnerStore } from '@/stores/learnerStore'
import { learnerAPI } from '@/lib/api'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Avatar } from '@/components/ui/Avatar'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import { Input } from '@/components/ui/Input'
import { EmptyState } from '@/components/ui/EmptyState'
import { ActivityLogSection } from '@/components/profile/ActivityLogSection'

export default function ProfilePage() {
  const { name, email, xp, streak, goalVector, topicProficiency, learningStyle, setLearner } = useLearnerStore()
  const qc = useQueryClient()
  const level = Math.floor(xp / 500) + 1
  const skillCount = Object.keys(topicProficiency).length

  const [editing, setEditing] = useState(false)
  const [editName, setEditName] = useState(name)
  const [editTargetRole, setEditTargetRole] = useState('')
  const [editCurrentRole, setEditCurrentRole] = useState('')
  const [editGoals, setEditGoals] = useState<string[]>(goalVector)
  const [newGoal, setNewGoal] = useState('')

  const { data: profile } = useQuery({
    queryKey: ['learner', 'profile'],
    queryFn: () => learnerAPI.getProfile().then((r) => r.data),
    staleTime: 1000 * 60 * 5,
  })

  useEffect(() => {
    if (profile) {
      setEditTargetRole(profile.target_role ?? '')
      setEditCurrentRole(profile.current_role ?? '')
    }
  }, [profile])

  const updateMutation = useMutation({
    mutationFn: (data: Parameters<typeof learnerAPI.updateProfile>[0]) =>
      learnerAPI.updateProfile(data).then((r) => r.data),
    onSuccess: (updated) => {
      if (updated.name) setLearner({ name: updated.name })
      if (updated.goal_vector) setLearner({ goalVector: updated.goal_vector })
      qc.invalidateQueries({ queryKey: ['learner', 'profile'] })
      toast.success('Profile updated')
      setEditing(false)
    },
    onError: () => toast.error('Could not save changes'),
  })

  const handleSave = () => {
    if (!editName.trim() || editName.trim().length < 2) {
      toast.error('Name must be at least 2 characters')
      return
    }
    updateMutation.mutate({
      name: editName.trim(),
      goal_vector: editGoals,
      target_role: editTargetRole.trim() || undefined,
      current_role: editCurrentRole.trim() || undefined,
    })
  }

  const handleAddGoal = () => {
    const g = newGoal.trim()
    if (!g || editGoals.includes(g) || editGoals.length >= 10) return
    setEditGoals([...editGoals, g])
    setNewGoal('')
  }

  const handleRemoveGoal = (g: string) => {
    setEditGoals(editGoals.filter((x) => x !== g))
  }

  const handleCancel = () => {
    setEditName(name)
    setEditTargetRole(profile?.target_role ?? '')
    setEditCurrentRole(profile?.current_role ?? '')
    setEditGoals(goalVector)
    setNewGoal('')
    setEditing(false)
  }

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1240, margin: '0 auto' }}>
      <div style={{ marginBottom: 18, display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
        <div>
          <div className="caps fg-3">Account</div>
          <h1 className="serif" style={{ fontSize: 36, fontWeight: 400, margin: 0, letterSpacing: '-0.02em' }}>Profile</h1>
        </div>
        {!editing && (
          <Button size="sm" variant="secondary" icon="edit" onClick={() => {
            setEditName(name)
            setEditTargetRole(profile?.target_role ?? '')
            setEditCurrentRole(profile?.current_role ?? '')
            setEditGoals(goalVector)
            setEditing(true)
          }}>
            Edit profile
          </Button>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 14 }}>
        <ActivityLogSection />

        {/* Right column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Learner info */}
          <Card padding="md">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
              <Avatar name={name || '?'} size={40} status="online" />
              <div style={{ flex: 1, minWidth: 0 }}>
                {editing ? (
                  <Input
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    placeholder="Your name"
                    style={{ fontSize: 14, fontWeight: 600 }}
                  />
                ) : (
                  <div className="t-md fg-0" style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {name || 'Learner'}
                  </div>
                )}
                <div className="t-xs fg-3" style={{ marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {email || '—'}
                </div>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <div style={{ padding: '8px 0', borderTop: '1px solid var(--line-1)' }}>
                <div className="caps fg-3">Level</div>
                <div className="serif" style={{ fontSize: 20, marginTop: 2 }}>{level}</div>
              </div>
              <div style={{ padding: '8px 0', borderTop: '1px solid var(--line-1)' }}>
                <div className="caps fg-3">XP</div>
                <div className="serif" style={{ fontSize: 20, marginTop: 2 }}>{xp.toLocaleString()}</div>
              </div>
              <div style={{ padding: '8px 0' }}>
                <div className="caps fg-3">Streak</div>
                <div className="serif" style={{ fontSize: 20, marginTop: 2, display: 'flex', alignItems: 'center', gap: 4 }}>
                  <Icon name="flame" size={16} />{streak}d
                </div>
              </div>
              <div style={{ padding: '8px 0' }}>
                <div className="caps fg-3">Skills</div>
                <div className="serif" style={{ fontSize: 20, marginTop: 2 }}>{skillCount}</div>
              </div>
            </div>
          </Card>

          {/* Career info */}
          {editing ? (
            <Card padding="md">
              <div className="caps fg-2" style={{ marginBottom: 10 }}>Career details</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div>
                  <div className="t-xs fg-3" style={{ marginBottom: 4 }}>Target role</div>
                  <Input
                    value={editTargetRole}
                    onChange={(e) => setEditTargetRole(e.target.value)}
                    placeholder="e.g. Senior ML Engineer"
                  />
                </div>
                <div>
                  <div className="t-xs fg-3" style={{ marginBottom: 4 }}>Current role</div>
                  <Input
                    value={editCurrentRole}
                    onChange={(e) => setEditCurrentRole(e.target.value)}
                    placeholder="e.g. Junior Developer"
                  />
                </div>
              </div>
            </Card>
          ) : (profile?.target_role || profile?.current_role) ? (
            <Card padding="md">
              <div className="caps fg-2" style={{ marginBottom: 8 }}>Career details</div>
              {profile?.target_role && (
                <div style={{ marginBottom: 6 }}>
                  <div className="t-xs fg-3">Target role</div>
                  <div className="t-sm fg-0" style={{ fontWeight: 500, marginTop: 2 }}>{profile.target_role}</div>
                </div>
              )}
              {profile?.current_role && (
                <div>
                  <div className="t-xs fg-3">Current role</div>
                  <div className="t-sm fg-0" style={{ fontWeight: 500, marginTop: 2 }}>{profile.current_role}</div>
                </div>
              )}
            </Card>
          ) : null}

          {/* Goals */}
          <Card padding="md">
            <div className="caps fg-2" style={{ marginBottom: 8 }}>Learning goals</div>
            {editing ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {editGoals.map((g) => (
                    <button
                      key={g}
                      onClick={() => handleRemoveGoal(g)}
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: 4,
                        padding: '3px 8px', borderRadius: 'var(--r-pill)',
                        border: '1px solid var(--line-2)', background: 'var(--paper-2)',
                        color: 'var(--ink-1)', fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
                      }}
                    >
                      {g} <Icon name="close" size={10} />
                    </button>
                  ))}
                </div>
                {editGoals.length < 10 && (
                  <div style={{ display: 'flex', gap: 6 }}>
                    <Input
                      value={newGoal}
                      onChange={(e) => setNewGoal(e.target.value)}
                      placeholder="Add a goal…"
                      onKeyDown={(e) => e.key === 'Enter' && handleAddGoal()}
                      style={{ flex: 1 }}
                    />
                    <Button size="sm" variant="secondary" onClick={handleAddGoal}>Add</Button>
                  </div>
                )}
              </div>
            ) : goalVector.length === 0 ? (
              <EmptyState
                icon="target"
                title="No goals set yet"
                body="Add learning goals to track your progress."
                action={{ label: 'Edit profile', onClick: () => setEditing(true) }}
                size="sm"
              />
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {goalVector.map((g) => <Badge key={g} size="sm" tone="outline">{g}</Badge>)}
              </div>
            )}
          </Card>

          {/* Learning style */}
          <Card padding="md">
            <div className="caps fg-2" style={{ marginBottom: 8 }}>Learning style</div>
            <Badge size="sm" tone="accent">{learningStyle}</Badge>
          </Card>

          {/* Edit actions */}
          {editing && (
            <div style={{ display: 'flex', gap: 8 }}>
              <Button variant="primary" full onClick={handleSave} loading={updateMutation.isPending}>Save changes</Button>
              <Button variant="secondary" onClick={handleCancel}>Cancel</Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
