import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { ChatColumn } from './ChatColumn'
import { useNotes } from '@/lib/hooks/use-notes'
import { useMultimodalChat } from '@/lib/hooks/use-multimodal'

// Mock the hooks
vi.mock('@/lib/hooks/use-notes')
vi.mock('@/lib/hooks/use-multimodal')
vi.mock('@/components/source/ChatPanel', () => ({
  ChatPanel: () => <div data-testid="chat-panel" />
}))

// Type-safe mock factory for useNotes hook
function createNotesMock(overrides: { isLoading?: boolean } = {}) {
  return {
    data: [],
    isLoading: overrides.isLoading ?? false,
  } as unknown as ReturnType<typeof useNotes>
}

// Type-safe mock factory for useMultimodalChat hook
function createChatMock() {
  return {
    messages: [],
    isSending: false,
    tokenCount: 0,
    charCount: 0,
    sessions: [],
    currentSessionId: null,
    sendMessage: vi.fn(),
    setModelOverride: vi.fn(),
    createSession: vi.fn(),
    updateSession: vi.fn(),
    deleteSession: vi.fn(),
    switchSession: vi.fn(),
  } as unknown as ReturnType<typeof useMultimodalChat>
}

describe('ChatColumn', () => {
  const baseProps = {
    notebookId: 'test-notebook',
    contextSelections: {
      sources: {},
      notes: {}
    },
    sources: [],
  }

  it('shows loading spinner when fetching data', () => {
    vi.mocked(useNotes).mockReturnValue(createNotesMock({ isLoading: true }))
    vi.mocked(useMultimodalChat).mockReturnValue(createChatMock())

    render(<ChatColumn {...baseProps} sourcesLoading={true} />)

    // Should show loading spinner
    expect(screen.getByTestId('loading-spinner')).toBeInTheDocument()
  })

  it('renders chat panel when data is loaded', () => {
    vi.mocked(useNotes).mockReturnValue(createNotesMock({ isLoading: false }))
    vi.mocked(useMultimodalChat).mockReturnValue(createChatMock())

    render(<ChatColumn {...baseProps} sourcesLoading={false} />)

    // Should show chat panel
    expect(screen.getByTestId('chat-panel')).toBeInTheDocument()
  })
})
