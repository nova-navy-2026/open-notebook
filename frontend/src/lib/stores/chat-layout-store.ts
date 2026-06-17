import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface ChatLayoutState {
  // Whether the OpenWebUI-style session history rail is collapsed to its
  // icon-only strip. Persisted so the user's preference survives reloads,
  // mirroring the notebook columns store.
  sessionRailCollapsed: boolean
  toggleSessionRail: () => void
  setSessionRailCollapsed: (collapsed: boolean) => void
}

export const useChatLayoutStore = create<ChatLayoutState>()(
  persist(
    (set) => ({
      sessionRailCollapsed: false,
      toggleSessionRail: () =>
        set((state) => ({ sessionRailCollapsed: !state.sessionRailCollapsed })),
      setSessionRailCollapsed: (collapsed) =>
        set({ sessionRailCollapsed: collapsed }),
    }),
    {
      name: 'chat-layout-storage',
    },
  ),
)
