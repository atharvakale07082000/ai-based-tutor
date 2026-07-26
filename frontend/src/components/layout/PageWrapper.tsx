import { useLocation } from 'react-router-dom'

interface PageWrapperProps {
  children: React.ReactNode
}

// Thin wrapper that plays the page-enter transition — shell layout lives in App.tsx
export function PageWrapper({ children }: PageWrapperProps) {
  const location = useLocation()
  return (
    <div key={location.pathname} className="page-enter" style={{ height: '100%' }}>
      {children}
    </div>
  )
}
