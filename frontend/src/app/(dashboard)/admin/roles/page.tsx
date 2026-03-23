"use client";

import { useState } from "react";
import { RoleManagementComponent } from "@/components/admin/RoleManagementComponent";
import { UserCreationDialog } from "@/components/admin/UserCreationDialog";
import { PermissionsManagementComponent } from "@/components/admin/PermissionsManagementComponent";
import { ProtectedRouteGuard } from "@/lib/hooks/use-authorization";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";
import { useRouter } from "next/navigation";

export default function RolesAdminPage() {
  const [refreshKey, setRefreshKey] = useState(0);
  const router = useRouter();

  return (
    <ProtectedRouteGuard requiredRole="admin">
      <div className="container mx-auto py-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">
              User & Permissions Management
            </h1>
            <p className="text-muted-foreground mt-2">
              Manage users, roles, and granular permissions
            </p>
          </div>
          <div className="flex items-center gap-4">
            <UserCreationDialog
              onUserCreated={() => setRefreshKey((k) => k + 1)}
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => router.back()}
              className="gap-2"
            >
              <ArrowLeft className="h-4 w-4" />
              Back
            </Button>
          </div>
        </div>

        <div className="space-y-6">
          <RoleManagementComponent key={refreshKey} />
          <PermissionsManagementComponent />
        </div>
      </div>
    </ProtectedRouteGuard>
  );
}
