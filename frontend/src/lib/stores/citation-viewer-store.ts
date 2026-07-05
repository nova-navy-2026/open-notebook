import { create } from 'zustand'
import { CitationTarget } from '@/lib/types/citations'

interface CitationViewerState {
  isOpen: boolean
  target: CitationTarget | null
  openCitation: (target: CitationTarget) => void
  closeCitation: () => void
}

export const useCitationViewerStore = create<CitationViewerState>()((set) => ({
  isOpen: false,
  target: null,
  openCitation: (target) => set({ isOpen: true, target }),
  // Keep target until next open so the close animation doesn't flash empty content
  closeCitation: () => set({ isOpen: false }),
}))
