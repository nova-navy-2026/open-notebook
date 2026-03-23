"use client";

import React, { createContext, useContext } from "react";
import { useAuthStore, UserRole } from "@/lib/stores/auth-store";

interface RBACContextType {
  hasRole: (role: UserRole) => boolean;
  hasPermission: (permission: string) => boolean;
  isAdmin: boolean;
  isEditor: boolean;
  isViewer: boolean;
  userRoles: UserRole[];
}

const RBACContext = createContext<RBACContextType | undefined>(undefined);

export function RBACProvider({ children }: { children: React.ReactNode }) {
  const {
    user,
    hasRole: storeHasRole,
    hasPermission: storeHasPermission,
  } = useAuthStore();

  const contextValue: RBACContextType = {
    hasRole: storeHasRole,
    hasPermission: storeHasPermission,
    isAdmin: storeHasRole("admin"),
    isEditor: storeHasRole("editor"),
    isViewer: storeHasRole("viewer"),
    userRoles: user?.roles || [],
  };

  return (
    <RBACContext.Provider value={contextValue}>{children}</RBACContext.Provider>
  );
}

export function useRBAC() {
  const context = useContext(RBACContext);
  if (!context) {
    throw new Error("useRBAC must be used within RBACProvider");
  }
  return context;
}

/**
 * Component to render children only if user has specific role
 */
export function RequireRole({
  role,
  children,
  fallback = null,
}: {
  role: UserRole | UserRole[];
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  const { hasRole } = useRBAC();
  const roles = Array.isArray(role) ? role : [role];

  const hasRequiredRole = roles.some((r) => hasRole(r));

  return hasRequiredRole ? children : fallback;
}

/**
 * Component to render children only if user has specific permission
 */
export function RequirePermission({
  permission,
  children,
  fallback = null,
}: {
  permission: string;
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  const { hasPermission } = useRBAC();

  return hasPermission(permission) ? children : fallback;
}
