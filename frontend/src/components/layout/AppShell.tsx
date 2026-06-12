'use client'

import { useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import { AppSidebar } from './AppSidebar'
import { SetupBanner } from './SetupBanner'
import { useSidebarStore } from '@/lib/stores/sidebar-store'

interface AppShellProps {
  children: React.ReactNode
}

export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname()
  const { isCollapsed, setCollapsed } = useSidebarStore()

  // Immersive notebook view (NotebookLM-style): when inside a specific
  // notebook (/notebooks/<id>) the sidebar is kept available but collapsed
  // by default so the notebook takes over most of the screen. The user can
  // expand it again from the collapse toggle.
  const isImmersiveNotebook = /^\/notebooks\/.+/.test(pathname ?? '')

  // Remember the sidebar state before entering immersive mode so we can
  // restore it when leaving the notebook.
  const prevCollapsedRef = useRef<boolean | null>(null)
  const wasImmersiveRef = useRef(false)

  useEffect(() => {
    if (isImmersiveNotebook && !wasImmersiveRef.current) {
      // Entering a notebook: remember current state and collapse.
      prevCollapsedRef.current = isCollapsed
      setCollapsed(true)
      wasImmersiveRef.current = true
    } else if (!isImmersiveNotebook && wasImmersiveRef.current) {
      // Leaving a notebook: restore the previous sidebar state.
      if (prevCollapsedRef.current !== null) {
        setCollapsed(prevCollapsedRef.current)
      }
      prevCollapsedRef.current = null
      wasImmersiveRef.current = false
    }
  }, [isImmersiveNotebook, isCollapsed, setCollapsed])

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
        {!isImmersiveNotebook && <SetupBanner />}
        <div className="flex-1 overflow-auto w-full scroll-smooth">
          {children}
        </div>
      </main>
    </div>
  )
}
