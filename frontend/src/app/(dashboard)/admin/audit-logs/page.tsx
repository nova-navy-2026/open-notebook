"use client";

import { AuditLogViewer } from "@/components/admin/AuditLogViewer";
import { ProtectedRouteGuard } from "@/lib/hooks/use-authorization";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";
import { useRouter } from "next/navigation";

export default function AuditLogsAdminPage() {
  const router = useRouter();

  return (
    <ProtectedRouteGuard requiredRole="admin">
      <div className="container mx-auto py-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Audit Logs</h1>
            <p className="text-muted-foreground mt-2">
              Monitor system activities and user actions
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

        <AuditLogViewer />
      </div>
    </ProtectedRouteGuard>
  );
}
