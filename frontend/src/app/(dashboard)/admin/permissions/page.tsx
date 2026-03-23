"use client";

import { PermissionsManagementComponent } from "@/components/admin/PermissionsManagementComponent";
import { ProtectedRouteGuard } from "@/lib/hooks/use-authorization";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";
import { useRouter } from "next/navigation";

export default function PermissionsPage() {
  const router = useRouter();

  return (
    <ProtectedRouteGuard requiredRole="admin">
      <div className="container mx-auto py-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Permission Management</h1>
            <p className="text-muted-foreground mt-2">
              Configure granular permissions for each role
            </p>
          </div>
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

        <PermissionsManagementComponent />
      </div>
    </ProtectedRouteGuard>
  );
}
