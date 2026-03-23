"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/stores/auth-store";
import { UserRole } from "@/lib/stores/auth-store";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";

interface ProtectedRouteGuardProps {
  children: React.ReactNode;
  requiredRole?: UserRole | UserRole[];
  requiredPermission?: string;
  fallback?: React.ReactNode;
}

/**
 * Guard component to protect routes based on authentication, roles, or permissions
 */
export function ProtectedRouteGuard({
  children,
  requiredRole,
  requiredPermission,
  fallback,
}: ProtectedRouteGuardProps) {
  const router = useRouter();
  const { isAuthenticated, user, hasRole, hasPermission, hasHydrated } =
    useAuthStore();

  useEffect(() => {
    // Wait for hydration
    if (!hasHydrated) {
      return;
    }

    // Check authentication
    if (!isAuthenticated) {
      router.push("/login");
      return;
    }

    // Check role requirement
    if (requiredRole) {
      const roles = Array.isArray(requiredRole) ? requiredRole : [requiredRole];
      const hasRequiredRole = roles.some((role) => hasRole(role));

      if (!hasRequiredRole) {
        console.warn(`User lacks required role to access route`);
        router.push("/notebooks");
        return;
      }
    }

    // Check permission requirement
    if (requiredPermission && !hasPermission(requiredPermission)) {
      console.warn(`User lacks required permission: ${requiredPermission}`);
      router.push("/notebooks");
      return;
    }
  }, [
    isAuthenticated,
    hasHydrated,
    requiredRole,
    requiredPermission,
    hasRole,
    hasPermission,
    router,
  ]);

  // Show loading while checking auth
  if (!hasHydrated) {
    return <LoadingSpinner />;
  }

  // Check current auth state
  if (!isAuthenticated) {
    return fallback || null;
  }

  // Check role requirement
  if (requiredRole) {
    const roles = Array.isArray(requiredRole) ? requiredRole : [requiredRole];
    const hasRequiredRole = roles.some((role) => hasRole(role));

    if (!hasRequiredRole) {
      return (
        fallback || (
          <div className="flex items-center justify-center min-h-screen">
            <p className="text-muted-foreground">
              You don't have permission to access this page.
            </p>
          </div>
        )
      );
    }
  }

  // Check permission requirement
  if (requiredPermission && !hasPermission(requiredPermission)) {
    return (
      fallback || (
        <div className="flex items-center justify-center min-h-screen">
          <p className="text-muted-foreground">
            You don't have permission to access this resource.
          </p>
        </div>
      )
    );
  }

  return <>{children}</>;
}

/**
 * Hook to check if a user is authorized for a specific action
 */
export function useAuthorization() {
  const { user, hasRole, hasPermission } = useAuthStore();

  return {
    isAuthenticated: !!user,
    user,
    hasRole,
    hasPermission,
    isAdmin: hasRole("admin"),
    isEditor: hasRole("editor"),
    isViewer: hasRole("viewer"),
  };
}
