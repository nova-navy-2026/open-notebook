import '@testing-library/jest-dom'
import { vi } from 'vitest'
import { enUS } from '../lib/locales/en-US'

// Mock next/navigation
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '',
  useSearchParams: () => new URLSearchParams(),
}))

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(), // Deprecated
    removeListener: vi.fn(), // Deprecated
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// Mock @/lib/hooks/use-translation with full locale structure
vi.mock('../lib/hooks/use-translation', () => {
  const t = (key: string) => key
  Object.assign(t, enUS)
  
  return {
    useTranslation: () => ({
      t,
      language: 'en-US',
      setLanguage: vi.fn(),
    }),
  }
})

// Mock @/lib/hooks/use-auth
vi.mock('@/lib/hooks/use-auth', () => ({
  useAuth: vi.fn(() => ({
    user: { id: '1', email: 'test@example.com' },
    logout: vi.fn(),
    isLoading: false,
  })),
}))

// Mock @/lib/stores/sidebar-store
vi.mock('@/lib/stores/sidebar-store', () => ({
  useSidebarStore: vi.fn(() => ({
    isCollapsed: false,
    toggleCollapse: vi.fn(),
  })),
}))

// Mock @/lib/hooks/use-create-dialogs
vi.mock('@/lib/hooks/use-create-dialogs', () => ({
  useCreateDialogs: vi.fn(() => ({
    openSourceDialog: vi.fn(),
    openNotebookDialog: vi.fn(),
    openPodcastDialog: vi.fn(),
  })),
}))

// Mock @/components/providers/ThemeProvider so components using useTheme() can
// render without a ThemeProvider wrapper in unit tests.
vi.mock('@/components/providers/ThemeProvider', () => ({
  useTheme: vi.fn(() => ({
    theme: 'light',
    resolvedTheme: 'light',
    setTheme: vi.fn(),
  })),
  ThemeProvider: ({ children }: { children: React.ReactNode }) => children,
}))

// Mock @/lib/contexts/rbac-context so components using useRBAC() can render
// without an RBACProvider wrapper in unit tests. Defaults to an admin view;
// individual tests can override useRBAC via vi.mocked().
vi.mock('@/lib/contexts/rbac-context', () => ({
  useRBAC: vi.fn(() => ({
    hasRole: vi.fn(() => true),
    hasPermission: vi.fn(() => true),
    isAdmin: true,
    isEditor: true,
    isViewer: true,
    userRoles: ['admin'],
  })),
  RBACProvider: ({ children }: { children: React.ReactNode }) => children,
  RequireRole: ({ children }: { children: React.ReactNode }) => children,
  RequirePermission: ({ children }: { children: React.ReactNode }) => children,
}))
