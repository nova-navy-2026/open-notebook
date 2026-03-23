"use client";

import { StatusDashboard } from "@/components/admin/StatusDashboard";
import { ProtectedRouteGuard } from "@/lib/hooks/use-authorization";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { Users, Shield, Activity, Settings, ArrowLeft } from "lucide-react";
import { useRouter } from "next/navigation";

export default function AdminDashboardPage() {
  const router = useRouter();

  return (
    <ProtectedRouteGuard requiredRole="admin">
      <div className="container mx-auto py-8">
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-4xl font-bold">Admin Dashboard</h1>
            <p className="text-muted-foreground mt-2">
              Manage system, monitor health, and configure access
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

        {/* Quick Actions */}
        <div className="grid md:grid-cols-4 gap-4 mb-8">
          <Card className="cursor-pointer hover:shadow-lg transition-shadow">
            <Link href="/admin/roles">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">Users & Roles</CardTitle>
                  <Users className="h-5 w-5 text-blue-600" />
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  Manage users and assign roles
                </p>
              </CardContent>
            </Link>
          </Card>

          <Card className="cursor-pointer hover:shadow-lg transition-shadow">
            <Link href="/admin/permissions">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">Permissions</CardTitle>
                  <Shield className="h-5 w-5 text-green-600" />
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  Configure role permissions
                </p>
              </CardContent>
            </Link>
          </Card>

          <Card className="cursor-pointer hover:shadow-lg transition-shadow">
            <Link href="/admin/audit-logs">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">Audit Logs</CardTitle>
                  <Activity className="h-5 w-5 text-orange-600" />
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  View system activities
                </p>
              </CardContent>
            </Link>
          </Card>

          <Card className="cursor-pointer hover:shadow-lg transition-shadow">
            <Link href="/settings">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">Settings</CardTitle>
                  <Settings className="h-5 w-5 text-purple-600" />
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">System settings</p>
              </CardContent>
            </Link>
          </Card>
        </div>

        {/* Health Status */}
        <StatusDashboard />
      </div>
    </ProtectedRouteGuard>
  );
}
