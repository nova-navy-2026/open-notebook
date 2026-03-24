import { create } from "zustand";
import { persist } from "zustand/middleware";
import { getApiUrl } from "@/lib/config";

export type UserRole = "admin" | "editor" | "viewer";

export interface UserInfo {
  id: string;
  email: string;
  name?: string;
  roles: UserRole[];
  provider?: "local" | "azure" | "google" | "github";
  avatar?: string;
}

interface AuthState {
  isAuthenticated: boolean;
  token: string | null;
  user: UserInfo | null;
  isLoading: boolean;
  error: string | null;
  lastAuthCheck: number | null;
  isCheckingAuth: boolean;
  hasHydrated: boolean;
  authRequired: boolean | null;
  // New additions for OAuth and RBAC
  oauthState?: string;
  oauthProvider?: "azure" | "google" | "github";

  setHasHydrated: (state: boolean) => void;
  checkAuthRequired: () => Promise<boolean>;
  login: (password: string) => Promise<boolean>;
  loginWithOAuth: (provider: "azure" | "google" | "github") => Promise<string>;
  handleOAuthCallback: (
    code: string,
    state: string,
    provider: "azure" | "google" | "github",
  ) => Promise<boolean>;
  logout: () => void;
  checkAuth: () => Promise<boolean>;
  fetchUserInfo: () => Promise<UserInfo | null>;
  hasRole: (role: UserRole) => boolean;
  hasPermission: (permission: string) => boolean;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      isAuthenticated: false,
      token: null,
      user: null,
      isLoading: false,
      error: null,
      lastAuthCheck: null,
      isCheckingAuth: false,
      hasHydrated: false,
      authRequired: null,

      setHasHydrated: (state: boolean) => {
        set({ hasHydrated: state });
      },

      checkAuthRequired: async () => {
        try {
          const apiUrl = await getApiUrl();
          const response = await fetch(`${apiUrl}/api/auth/status`, {
            cache: "no-store",
          });

          if (!response.ok) {
            throw new Error(`Auth status check failed: ${response.status}`);
          }

          const data = await response.json();
          const required = data.auth_enabled || false;
          set({ authRequired: required });

          // If auth is not required, mark as authenticated
          if (!required) {
            set({ isAuthenticated: true, token: "not-required" });
          }

          return required;
        } catch (error) {
          console.error("Failed to check auth status:", error);

          // If it's a network error, set a more helpful error message
          if (
            error instanceof TypeError &&
            error.message.includes("Failed to fetch")
          ) {
            set({
              error:
                "Unable to connect to server. Please check if the API is running.",
              authRequired: null, // Don't assume auth is required if we can't connect
            });
          } else {
            // For other errors, default to requiring auth to be safe
            set({ authRequired: true });
          }

          // Re-throw the error so the UI can handle it
          throw error;
        }
      },

      login: async (password: string) => {
        set({ isLoading: true, error: null });
        try {
          const apiUrl = await getApiUrl();

          // Call local login endpoint
          const response = await fetch(`${apiUrl}/api/auth/login/local`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              email: "admin@open-notebook.local",
              password,
            }),
          });

          if (response.ok) {
            const data = await response.json();
            const token = data.access_token || data.token;

            // Fetch user info
            const userResponse = await fetch(`${apiUrl}/api/auth/me`, {
              headers: {
                Authorization: `Bearer ${token}`,
                "Content-Type": "application/json",
              },
            });

            let user = null;
            if (userResponse.ok) {
              user = await userResponse.json();
            }

            set({
              isAuthenticated: true,
              token,
              user: user || {
                id: "admin",
                email: "admin@local",
                roles: ["admin"],
                provider: "local",
              },
              isLoading: false,
              lastAuthCheck: Date.now(),
              error: null,
            });
            return true;
          } else {
            let errorMessage = "Authentication failed";
            if (response.status === 401) {
              errorMessage = "Invalid password. Please try again.";
            } else if (response.status === 403) {
              errorMessage = "Access denied. Please check your credentials.";
            } else if (response.status >= 500) {
              errorMessage = "Server error. Please try again later.";
            } else {
              errorMessage = `Authentication failed (${response.status})`;
            }

            set({
              error: errorMessage,
              isLoading: false,
              isAuthenticated: false,
              token: null,
              user: null,
            });
            return false;
          }
        } catch (error) {
          console.error("Network error during auth:", error);
          let errorMessage = "Authentication failed";

          if (
            error instanceof TypeError &&
            error.message.includes("Failed to fetch")
          ) {
            errorMessage =
              "Unable to connect to server. Please check if the API is running.";
          } else if (error instanceof Error) {
            errorMessage = `Network error: ${error.message}`;
          } else {
            errorMessage = "An unexpected error occurred during authentication";
          }

          set({
            error: errorMessage,
            isLoading: false,
            isAuthenticated: false,
            token: null,
            user: null,
          });
          return false;
        }
      },

      loginWithOAuth: async (provider: "azure" | "google" | "github") => {
        set({ isLoading: true, error: null, oauthProvider: provider });
        try {
          const apiUrl = await getApiUrl();
          const state = Math.random().toString(36).substring(7); // Simple state generation

          set({ oauthState: state });

          const response = await fetch(
            `${apiUrl}/api/auth/oauth/${provider}/init`,
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
              },
              body: JSON.stringify({
                state,
                redirect_uri: `${window.location.origin}/auth/oauth/callback`,
              }),
            },
          );

          if (response.ok) {
            const data = await response.json();
            return data.authorization_url;
          } else {
            throw new Error(`OAuth initialization failed: ${response.status}`);
          }
        } catch (error) {
          const errorMessage =
            error instanceof Error
              ? error.message
              : "OAuth initialization failed";
          set({ error: errorMessage, isLoading: false });
          throw error;
        }
      },

      handleOAuthCallback: async (
        code: string,
        state: string,
        provider: "azure" | "google" | "github",
      ) => {
        set({ isLoading: true, error: null });
        try {
          const apiUrl = await getApiUrl();

          const response = await fetch(
            `${apiUrl}/api/auth/oauth/${provider}/callback`,
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
              },
              body: JSON.stringify({
                code,
                state,
                redirect_uri: `${window.location.origin}/auth/oauth/callback`,
              }),
            },
          );

          if (response.ok) {
            const data = await response.json();
            const token = data.access_token || data.token;

            // Fetch user info
            const userResponse = await fetch(`${apiUrl}/api/auth/me`, {
              headers: {
                Authorization: `Bearer ${token}`,
                "Content-Type": "application/json",
              },
            });

            let user = null;
            if (userResponse.ok) {
              user = await userResponse.json();
              user.provider = provider;
            }

            set({
              isAuthenticated: true,
              token,
              user: user || {
                id: provider,
                email: "user@provider.com",
                roles: ["viewer"],
                provider,
              },
              isLoading: false,
              lastAuthCheck: Date.now(),
              error: null,
              oauthState: undefined,
              oauthProvider: undefined,
            });
            return true;
          } else {
            const errorData = await response.json().catch(() => ({}));
            const errorMessage = errorData.detail || "OAuth callback failed";

            set({
              error: errorMessage,
              isLoading: false,
              isAuthenticated: false,
              token: null,
              user: null,
            });
            return false;
          }
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : "OAuth callback failed";
          set({
            error: errorMessage,
            isLoading: false,
            isAuthenticated: false,
            token: null,
            user: null,
          });
          return false;
        }
      },

      logout: async () => {
        const state = get();
        if (state.token && state.token !== "not-required") {
          try {
            const apiUrl = await getApiUrl();
            await fetch(`${apiUrl}/api/auth/logout`, {
              method: "POST",
              headers: {
                Authorization: `Bearer ${state.token}`,
                "Content-Type": "application/json",
              },
            }).catch(() => {}); // Ignore errors on logout
          } catch {
            // Silently fail, logout locally anyway
          }
        }

        set({
          isAuthenticated: false,
          token: null,
          user: null,
          error: null,
          oauthState: undefined,
          oauthProvider: undefined,
        });
      },

      fetchUserInfo: async () => {
        const state = get();
        if (!state.token || !state.isAuthenticated) {
          return null;
        }

        try {
          const apiUrl = await getApiUrl();
          const response = await fetch(`${apiUrl}/api/auth/me`, {
            headers: {
              Authorization: `Bearer ${state.token}`,
              "Content-Type": "application/json",
            },
          });

          if (response.ok) {
            const user = await response.json();
            set({ user });
            return user;
          }
        } catch (error) {
          console.error("Failed to fetch user info:", error);
        }

        return null;
      },

      hasRole: (role: UserRole) => {
        const state = get();
        return state.user?.roles?.includes(role) ?? false;
      },

      hasPermission: (permission: string) => {
        const state = get();
        if (!state.user) return false;

        const roles = state.user.roles ?? [];

        // Admin has all permissions
        if (roles.includes("admin")) return true;

        // Check specific permissions based on role
        const rolePermissions: Record<UserRole, string[]> = {
          admin: ["*"],
          editor: ["read", "write", "delete-own", "search", "view-shared"],
          viewer: ["read", "search", "view-shared"],
        };

        for (const role of roles) {
          if (
            rolePermissions[role]?.includes(permission) ||
            rolePermissions[role]?.includes("*")
          ) {
            return true;
          }
        }

        return false;
      },

      checkAuth: async () => {
        const state = get();
        const { token, lastAuthCheck, isCheckingAuth, isAuthenticated } = state;

        // If already checking, return current auth state
        if (isCheckingAuth) {
          return isAuthenticated;
        }

        // If no token, not authenticated
        if (!token) {
          return false;
        }

        // If we checked recently (within 30 seconds) and are authenticated, skip
        const now = Date.now();
        if (isAuthenticated && lastAuthCheck && now - lastAuthCheck < 30000) {
          return true;
        }

        set({ isCheckingAuth: true });

        try {
          const apiUrl = await getApiUrl();

          const response = await fetch(`${apiUrl}/api/auth/verify`, {
            method: "POST",
            headers: {
              Authorization: `Bearer ${token}`,
              "Content-Type": "application/json",
            },
          });

          if (response.ok) {
            set({
              isAuthenticated: true,
              lastAuthCheck: now,
              isCheckingAuth: false,
            });
            return true;
          } else {
            set({
              isAuthenticated: false,
              token: null,
              user: null,
              lastAuthCheck: null,
              isCheckingAuth: false,
            });
            return false;
          }
        } catch (error) {
          console.error("checkAuth error:", error);
          set({
            isAuthenticated: false,
            token: null,
            user: null,
            lastAuthCheck: null,
            isCheckingAuth: false,
          });
          return false;
        }
      },
    }),
    {
      name: "auth-storage",
      partialize: (state) => ({
        token: state.token,
        isAuthenticated: state.isAuthenticated,
        user: state.user,
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true);
      },
    },
  ),
);
