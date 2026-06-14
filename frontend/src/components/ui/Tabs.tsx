import { cva } from 'class-variance-authority'
import { cn } from '@/lib/cn'
import { Icon } from './Icon'

interface TabItem {
  value: string
  label: string
  icon?: string
  count?: number
}

interface TabsProps {
  tabs: TabItem[]
  value: string
  onChange: (v: string) => void
  variant?: 'underline' | 'segmented'
}

const segTab = cva(
  'seg-i whitespace-nowrap rounded-[var(--r-1)] px-2.5 py-1 text-[12px] font-medium transition-[background-color,color,box-shadow] duration-[var(--dur-fast)] ease-[var(--ease-out)]',
  {
    variants: {
      active: {
        true: 'bg-paper-0 text-ink-0 shadow-[var(--shadow-1)]',
        false: 'bg-transparent text-ink-2',
      },
    },
  }
)

const underlineTab = cva(
  'tab-i -mb-px inline-flex items-center gap-1.5 whitespace-nowrap px-3 py-2 text-[13px] font-medium border-b-2 transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]',
  {
    variants: {
      active: {
        true: 'text-ink-0 border-ink-0',
        false: 'text-ink-2 border-transparent',
      },
    },
  }
)

export function Tabs({ tabs, value, onChange, variant = 'underline' }: TabsProps) {
  if (variant === 'segmented') {
    return (
      <div role="tablist" className="inline-flex gap-0.5 rounded-[var(--r-2)] border border-line-1 bg-paper-2 p-0.5">
        {tabs.map((t) => (
          <button
            key={t.value}
            role="tab"
            aria-selected={value === t.value}
            onClick={() => onChange(t.value)}
            className={cn(segTab({ active: value === t.value }), 'border-0 font-[inherit] cursor-pointer')}
          >
            {t.label}
          </button>
        ))}
      </div>
    )
  }

  return (
    <div role="tablist" className="flex gap-0 border-b border-line-1">
      {tabs.map((t) => (
        <button
          key={t.value}
          role="tab"
          aria-selected={value === t.value}
          onClick={() => onChange(t.value)}
          className={cn(underlineTab({ active: value === t.value }), 'bg-transparent border-x-0 border-t-0 font-[inherit] cursor-pointer')}
        >
          {t.icon && <Icon name={t.icon} size={13} />}
          {t.label}
          {t.count !== undefined && <span className="t-xs fg-3">{t.count}</span>}
        </button>
      ))}
    </div>
  )
}
