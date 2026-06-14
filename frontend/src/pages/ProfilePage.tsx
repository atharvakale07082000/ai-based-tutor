import { useLearnerStore } from '@/stores/learnerStore'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Avatar } from '@/components/ui/Avatar'
import { Icon } from '@/components/ui/Icon'
import { ActivityLogSection } from '@/components/profile/ActivityLogSection'

export default function ProfilePage() {
  const { name, email, xp, streak, goalVector, topicProficiency, learningStyle } = useLearnerStore()
  const level = Math.floor(xp / 500) + 1
  const skillCount = Object.keys(topicProficiency).length

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1240, margin: '0 auto' }}>
      <div style={{ marginBottom: 18 }}>
        <div className="caps fg-3">Account</div>
        <h1 className="serif" style={{ fontSize: 36, fontWeight: 400, margin: 0, letterSpacing: '-0.02em' }}>Profile</h1>
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
                <div className="t-md fg-0" style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {name || 'Learner'}
                </div>
                <div className="t-xs fg-3" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
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
                <div className="caps fg-3">Sub-skills</div>
                <div className="serif" style={{ fontSize: 20, marginTop: 2 }}>{skillCount}</div>
              </div>
            </div>
          </Card>

          {/* Goals */}
          <Card padding="md">
            <div className="caps fg-2" style={{ marginBottom: 8 }}>Learning goals</div>
            {goalVector.length === 0 ? (
              <div className="t-sm fg-3">No goals set yet.</div>
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
        </div>
      </div>
    </div>
  )
}
