import type { SVGProps } from 'react'

const PATHS: Record<string, string> = {
  home:      'M3 10.5L12 3l9 7.5V20a1 1 0 01-1 1h-5v-7h-6v7H4a1 1 0 01-1-1v-9.5z',
  feed:      'M4 6h16M4 12h16M4 18h10',
  book:      'M4 4h7a3 3 0 013 3v13a2 2 0 00-2-2H4V4zm16 0h-7a3 3 0 00-3 3v13a2 2 0 012-2h8V4z',
  chat:      'M21 12a8 8 0 01-12.5 6.6L3 20l1.4-5.5A8 8 0 1121 12z',
  quiz:      'M9 11l3 3 8-8M5 12v6a2 2 0 002 2h12a2 2 0 002-2v-6',
  progress:  'M3 20h18M6 16V10m4 6V6m4 10v-8m4 8V13',
  course:    'M3 7l9-4 9 4-9 4-9-4zm0 6l9 4 9-4M3 17l9 4 9-4',
  interview: 'M12 14a3 3 0 100-6 3 3 0 000 6zm0 2c-3 0-7 1.5-7 5v1h14v-1c0-3.5-4-5-7-5z',
  assistant: 'M12 2l1.5 4 4.5 1.5-4.5 1.5L12 13l-1.5-4L6 7.5 10.5 6 12 2zm6 11l1 2.5 2.5 1-2.5 1L18 20l-1-2.5L14.5 16.5 17 15.5 18 13z',
  admin:     'M12 1l8 4v6c0 5-3.5 9.5-8 11-4.5-1.5-8-6-8-11V5l8-4z',
  search:    'M11 19a8 8 0 100-16 8 8 0 000 16zm10 2l-4.3-4.3',
  plus:      'M12 5v14M5 12h14',
  chevR:     'M9 6l6 6-6 6',
  chevL:     'M15 6l-9 6 9 6',
  chevD:     'M6 9l6 6 6-6',
  chevU:     'M6 15l6-6 6 6',
  x:         'M6 6l12 12M18 6L6 18',
  check:     'M5 12l5 5L20 7',
  arrow:     'M5 12h14M13 6l6 6-6 6',
  arrowL:    'M19 12H5M11 6l-6 6 6 6',
  arrowUR:   'M5 19L19 5M19 17V5H7',
  arrowDR:   'M5 5l14 14M19 7v12H7',
  sun:       'M12 3v2M12 19v2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M3 12h2M19 12h2M5.6 18.4L7 17M17 7l1.4-1.4M12 8a4 4 0 100 8 4 4 0 000-8z',
  moon:      'M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z',
  cmd:       'M9 9V6a3 3 0 10-3 3h12a3 3 0 10-3-3v12a3 3 0 103-3H6a3 3 0 103 3V9z',
  play:      'M6 4l14 8-14 8V4z',
  pause:     'M6 5h4v14H6zM14 5h4v14h-4z',
  mic:       'M12 14a3 3 0 003-3V6a3 3 0 10-6 0v5a3 3 0 003 3zm-7-3a7 7 0 0014 0M12 18v3',
  image:     'M4 4h16v16H4zM4 16l5-5 4 4 3-3 4 4',
  send:      'M3 11l18-8-8 18-2-8-8-2z',
  sparkle:   'M12 3l1.5 5L18 9.5l-4.5 1.5L12 16l-1.5-5L6 9.5 10.5 8 12 3z',
  bolt:      'M13 2L4 14h7l-1 8 9-12h-7l1-8z',
  flame:     'M12 22c4 0 7-3 7-7 0-4-4-6-4-10 0 0-3 2-3 6-1.5-1-2-3-2-3s-4 2-4 7c0 4 2 7 6 7z',
  target:    'M12 21a9 9 0 110-18 9 9 0 010 18zm0-4a5 5 0 100-10 5 5 0 000 10zm0-4a1 1 0 100-2 1 1 0 000 2z',
  star:      'M12 2l3 7 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1 3-7z',
  bookmark:  'M5 3h14v18l-7-4-7 4V3z',
  clock:     'M12 21a9 9 0 100-18 9 9 0 000 18zm0-13v5l3 2',
  calendar:  'M3 8h18M5 4h14a2 2 0 012 2v13a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2z',
  settings:  'M12 8a4 4 0 100 8 4 4 0 000-8zm9 4l-2-1-1-2 1-2-2-2-2 1-2-1-1-2H8l-1 2-2 1-2-1-2 2 1 2-1 2-2 1v3l2 1 1 2-1 2 2 2 2-1 2 1 1 2h3l1-2 2-1 2 1 2-2-1-2 1-2 2-1v-3z',
  user:      'M12 12a4 4 0 100-8 4 4 0 000 8zm-7 9c0-4 3-7 7-7s7 3 7 7',
  users:     'M9 11a4 4 0 100-8 4 4 0 000 8zm9 0a3 3 0 100-6 3 3 0 000 6zM2 21c0-3.5 3-6 7-6s7 2.5 7 6m1-6c3 0 6 1 6 5',
  upload:    'M12 16V4M6 10l6-6 6 6M4 20h16',
  download:  'M12 4v12M6 10l6 6 6-6M4 20h16',
  trash:     'M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13',
  edit:      'M4 20h4l10-10-4-4L4 16v4zM14 6l4 4',
  filter:    'M3 5h18l-7 9v6l-4-2v-4L3 5z',
  sort:      'M7 4v16M3 8l4-4 4 4M17 20V4M13 16l4 4 4-4',
  layers:    'M12 2l10 5-10 5L2 7l10-5zm0 8l10 5-10 5L2 15l10-5z',
  code:      'M9 18l-6-6 6-6M15 6l6 6-6 6',
  grid:      'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  list:      'M9 6h12M9 12h12M9 18h12M4 6h.01M4 12h.01M4 18h.01',
  bell:      'M18 16v-5a6 6 0 10-12 0v5l-2 2v1h16v-1l-2-2zM10 21a2 2 0 004 0',
  eye:       'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zm10 3a3 3 0 100-6 3 3 0 000 6z',
  'eye-off': 'M17.9 17.9A10 10 0 012.1 6.1M1 1l22 22M9.88 9.88a3 3 0 004.24 4.24M10.73 5.08A10 10 0 0121.9 17.9M14.12 14.12A3 3 0 019.9 9.9M1 1l22 22',
  close:     'M6 6l12 12M18 6L6 18',
  logout:    'M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9',
  link:      'M10 14a5 5 0 007 0l3-3a5 5 0 00-7-7l-1 1M14 10a5 5 0 00-7 0l-3 3a5 5 0 007 7l1-1',
  folder:    'M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7z',
  tag:       'M3 12V3h9l9 9-9 9-9-9zm5-5a1 1 0 100-2 1 1 0 000 2z',
  info:      'M12 21a9 9 0 100-18 9 9 0 000 18zm0-13a1 1 0 100 2 1 1 0 000-2zm0 4v6',
  alert:     'M12 8v5M12 17h.01M5 21h14a2 2 0 001.7-3l-7-12a2 2 0 00-3.4 0l-7 12A2 2 0 005 21z',
  refresh:   'M3 12a9 9 0 0115-6.7L21 8M21 4v4h-4M21 12a9 9 0 01-15 6.7L3 16M3 20v-4h4',
  dot:       'M12 12m-3 0a3 3 0 106 0 3 3 0 10-6 0',
}

interface IconProps extends SVGProps<SVGSVGElement> {
  name: string
  size?: number
  strokeWidth?: number
}

export function Icon({ name, size = 16, strokeWidth = 1.5, className = '', ...props }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className as string}
      style={{ flexShrink: 0 }}
      {...props}
    >
      <path d={PATHS[name] ?? PATHS.dot} />
    </svg>
  )
}
