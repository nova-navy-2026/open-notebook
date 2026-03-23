"use client";

import { useState, useEffect } from "react";
import { useAuthStore } from "@/lib/stores/auth-store";
import { getApiUrl } from "@/lib/config";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { AlertCircle, Check } from "lucide-react";

interface PermissionSet {
  id: string;
  name: string;
  permissions: string[];
}

interface RolePermissions {
  admin: string[];
  editor: string[];
  viewer: string[];
}

const DEFAULT_ROLE_PERMISSIONS: RolePermissions = {
  admin: [
    "read",
    "write",
    "delete",
    "manage-users",
    "manage-roles",
    "view-audit",
    "export-audit",
  ],
  editor: ["read", "write", "delete-own", "search", "view-shared"],
  viewer: ["read", "search", "view-shared"],
};

export function PermissionsManagementComponent() {
  const { token } = useAuthStore();
  const [permissions, setPermissions] = useState<RolePermissions>(
    DEFAULT_ROLE_PERMISSIONS,
  );
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    const fetchPermissions = async () => {
      if (!token) return;

      try {
        setIsLoading(true);
        const apiUrl = await getApiUrl();

        const response = await fetch(`${apiUrl}/api/permissions`, {
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
        });

        if (response.ok) {
          const data = await response.json();
          setPermissions(data || DEFAULT_ROLE_PERMISSIONS);
        } else {
          // Use defaults if endpoint not available
          setPermissions(DEFAULT_ROLE_PERMISSIONS);
        }
        setError(null);
      } catch (err) {
        console.error("Failed to fetch permissions:", err);
        setPermissions(DEFAULT_ROLE_PERMISSIONS);
      } finally {
        setIsLoading(false);
      }
    };

    fetchPermissions();
  }, [token]);

  const handlePermissionChange = (
    role: "admin" | "editor" | "viewer",
    permission: string,
    checked: boolean,
  ) => {
    setPermissions((prev) => ({
      ...prev,
      [role]: checked
        ? [...prev[role], permission]
        : prev[role].filter((p) => p !== permission),
    }));
    setSuccess(false);
  };

  const handleSave = async () => {
    if (!token) return;

    try {
      setIsSaving(true);
      const apiUrl = await getApiUrl();

      const response = await fetch(`${apiUrl}/api/permissions`, {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(permissions),
      });

      if (!response.ok) {
        const statusText = response.statusText || "Unknown error";
        throw new Error(
          `Failed to save permissions: ${response.status} ${statusText}`,
        );
      }

      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
      setError(null);
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "Failed to save permissions";
      console.error("Permissions save error:", err);
      setError(errorMessage);
    } finally {
      setIsSaving(false);
    }
  };

  const allPermissions = [
    "read",
    "write",
    "delete",
    "delete-own",
    "search",
    "view-shared",
    "manage-users",
    "manage-roles",
    "view-audit",
    "export-audit",
  ];

  if (isLoading) {
    return <LoadingSpinner />;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Role Permissions</CardTitle>
        <CardDescription>
          Configure granular permissions for each role
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {error && (
          <div className="flex items-start gap-2 text-red-600 text-sm">
            <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {success && (
          <div className="flex items-center gap-2 text-green-600 text-sm">
            <Check className="h-4 w-4 flex-shrink-0" />
            <span>Permissions saved successfully</span>
          </div>
        )}

        <div className="grid md:grid-cols-3 gap-6">
          {(["admin", "editor", "viewer"] as const).map((role) => (
            <div key={role} className="border rounded-lg p-4 space-y-3">
              <div>
                <h3 className="font-semibold capitalize">{role}</h3>
                <p className="text-xs text-muted-foreground">
                  {role === "admin" && "Full system access"}
                  {role === "editor" && "Can create and modify"}
                  {role === "viewer" && "Read-only access"}
                </p>
              </div>

              <div className="space-y-2">
                {allPermissions.map((permission) => (
                  <div key={permission} className="flex items-center gap-2">
                    <Checkbox
                      id={`${role}-${permission}`}
                      checked={permissions[role].includes(permission)}
                      onCheckedChange={(checked) =>
                        handlePermissionChange(role, permission, !!checked)
                      }
                      disabled={isSaving}
                    />
                    <Label
                      htmlFor={`${role}-${permission}`}
                      className="text-sm cursor-pointer"
                    >
                      {permission
                        .split("-")
                        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
                        .join(" ")}
                    </Label>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="flex justify-end">
          <Button onClick={handleSave} disabled={isSaving}>
            {isSaving ? "Saving..." : "Save Permissions"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
