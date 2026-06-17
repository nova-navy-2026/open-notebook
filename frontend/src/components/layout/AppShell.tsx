'use client'

import { useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import { AppSidebar } from './AppSidebar'
import { SetupBanner } from './SetupBanner'
import { useSidebarStore } from '@/lib/stores/sidebar-store'

interface AppShellProps {
  children: React.ReactNode
}

// "Focus workspace" routes: surfaces that own their own multi-column workspace
// (their own session/source/notes side panels) and read better when the global
// menu shrinks to its icon rail. Entering one of these auto-collapses the global
// sidebar to 64px so the page takes over most of the screen; the user can always
// expand it again from the collapse toggle. This is the single primitive shared
// by the immersive notebook view (NotebookLM-style) and the chat view
// (OpenWebUI-style).
const FOCUS_ROUTE_PATTERNS = [
  /^\/notebooks\/.+/, // a specific notebook
  /^\/chat(\/.*)?$/, // global chat
]

const isFocusRoute = (pathname: string) =>
  FOCUS_ROUTE_PATTERNS.some((pattern) => pattern.test(pathname))

export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname()
  const { isCollapsed, setCollapsed } = useSidebarStore()

  const focusMode = isFocusRoute(pathname ?? '')

  // The SetupBanner stays hidden in the immersive notebook view (preserving the
  // prior behaviour); other focus routes keep it so the "configure models" nudge
  // is still reachable there.
  const isImmersiveNotebook = /^\/notebooks\/.+/.test(pathname ?? '')

  // Remember the sidebar state before entering focus mode so we can
  // restore it when leaving.
  const prevCollapsedRef = useRef<boolean | null>(null)
  const wasFocusedRef = useRef(false)

  useEffect(() => {
    if (focusMode && !wasFocusedRef.current) {
      // Entering a focus workspace: remember current state and collapse.
      prevCollapsedRef.current = isCollapsed
      setCollapsed(true)
      wasFocusedRef.current = true
    } else if (!focusMode && wasFocusedRef.current) {
      // Leaving the focus workspace: restore the previous sidebar state.
      if (prevCollapsedRef.current !== null) {
        setCollapsed(prevCollapsedRef.current)
      }
      prevCollapsedRef.current = null
      wasFocusedRef.current = false
    }
  }, [focusMode, isCollapsed, setCollapsed])

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
