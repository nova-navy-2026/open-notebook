'use client'

import { useEffect } from 'react'
import { AppSidebar } from './AppSidebar'
import { SetupBanner } from './SetupBanner'

interface AppShellProps {
  children: React.ReactNode
}

export function AppShell({ children }: AppShellProps) {
  useEffect(() => {
    // Disable automatic scroll restoration on navigation
    if ('scrollRestoration' in window.history) {
      window.history.scrollRestoration = 'manual'
    }
  }, [])

  return (
    <div className="flex h-dvh overflow-hidden w-full">
      <AppSidebar />
      <main className="flex-1 flex flex-col min-h-0 overflow-auto w-full scroll-smooth">
        <SetupBanner />
        <div className="flex-1 overflow-auto w-full scroll-smooth">
          {children}
        </div>
      </main>
    </div>
  )
}
