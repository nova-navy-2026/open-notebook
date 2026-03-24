"use client";

import { useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { StatusDashboard } from "@/components/admin/StatusDashboard";
import { RoleManagementComponent } from "@/components/admin/RoleManagementComponent";
import { UserCreationDialog } from "@/components/admin/UserCreationDialog";
import { PermissionsManagementComponent } from "@/components/admin/PermissionsManagementComponent";
import { AuditLogViewer } from "@/components/admin/AuditLogViewer";
import { ProtectedRouteGuard } from "@/lib/hooks/use-authorization";
import { AppShell } from "@/components/layout/AppShell";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Users, Shield, Activity, BarChart3 } from "lucide-react";

export default function AdminDashboardPage() {
  const searchParams = useSearchParams();
  const [refreshKey, setRefreshKey] = useState(0);
  const [activeTab, setActiveTab] = useState("overview");

  // Set active tab based on query parameter
  useEffect(() => {
    const tabParam = searchParams.get("tab");
    if (
      tabParam &&
      ["overview", "users", "permissions", "audit"].includes(tabParam)
    ) {
      setActiveTab(tabParam);
    }
  }, [searchParams]);

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        <ProtectedRouteGuard requiredRole="admin">
          <div className="container mx-auto py-8">
            <div className="mb-8">
              <h1 className="text-4xl font-bold">Admin Dashboard</h1>
              <p className="text-muted-foreground mt-2">
                Manage system, monitor health, and configure access
              </p>
            </div>

            <Tabs
              value={activeTab}
              onValueChange={setActiveTab}
              className="w-full"
            >
              <TabsList className="grid w-full grid-cols-4 mb-8">
                <TabsTrigger value="overview" className="gap-2">
                  <BarChart3 className="h-4 w-4" />
                  <span className="hidden sm:inline">Overview</span>
                </TabsTrigger>
                <TabsTrigger value="users" className="gap-2">
                  <Users className="h-4 w-4" />
                  <span className="hidden sm:inline">Users & Roles</span>
                </TabsTrigger>
                <TabsTrigger value="permissions" className="gap-2">
                  <Shield className="h-4 w-4" />
                  <span className="hidden sm:inline">Permissions</span>
                </TabsTrigger>
                <TabsTrigger value="audit" className="gap-2">
                  <Activity className="h-4 w-4" />
                  <span className="hidden sm:inline">Audit Logs</span>
                </TabsTrigger>
              </TabsList>

              {/* Overview Tab */}
              <TabsContent value="overview" className="space-y-6">
                <StatusDashboard />

                {/* Quick Actions */}
                <div className="grid md:grid-cols-4 gap-4">
                  <Card
                    className="cursor-pointer hover:shadow-lg transition-shadow"
                    onClick={() => setActiveTab("users")}
                  >
                    <CardHeader>
                      <div className="flex items-center justify-between">
                        <CardTitle className="text-base">
                          Users & Roles
                        </CardTitle>
                        <Users className="h-5 w-5 text-blue-600" />
                      </div>
                    </CardHeader>
                    <CardContent>
                      <p className="text-sm text-muted-foreground">
                        Manage users and assign roles
                      </p>
                    </CardContent>
                  </Card>

                  <Card
                    className="cursor-pointer hover:shadow-lg transition-shadow"
                    onClick={() => setActiveTab("permissions")}
                  >
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
                  </Card>

                  <Card
                    className="cursor-pointer hover:shadow-lg transition-shadow"
                    onClick={() => setActiveTab("audit")}
                  >
                    <CardHeader>
                      <div className="flex items-center justify-between">
                        <CardTitle className="text-base">Audit Logs</CardTitle>
                        <Activity className="h-5 w-5 text-orange-600" />
                      </div>
                    </CardHeader>
                    <CardContent>
                      <p className="text-sm text-muted-foreground">
                        Review system activities
                      </p>
                    </CardContent>
                  </Card>
                </div>
              </TabsContent>

              {/* Users & Roles Tab */}
              <TabsContent value="users" className="space-y-6">
                <div>
                  <div className="mb-6 flex items-center justify-between">
                    <div>
                      <h2 className="text-3xl font-bold">
                        User & Permissions Management
                      </h2>
                      <p className="text-muted-foreground mt-2">
                        Manage users, roles, and granular permissions
                      </p>
                    </div>
                    <UserCreationDialog
                      onUserCreated={() => setRefreshKey((k) => k + 1)}
                    />
                  </div>

                  <div className="space-y-6">
                    <RoleManagementComponent key={refreshKey} />
                    <PermissionsManagementComponent />
                  </div>
                </div>
              </TabsContent>

              {/* Permissions Tab */}
              <TabsContent value="permissions" className="space-y-6">
                <div>
                  <h2 className="text-3xl font-bold mb-2">
                    Permission Management
                  </h2>
                  <p className="text-muted-foreground mb-6">
                    Configure granular permissions for each role
                  </p>
                  <PermissionsManagementComponent />
                </div>
              </TabsContent>

              {/* Audit Logs Tab */}
              <TabsContent value="audit" className="space-y-6">
                <div>
                  <h2 className="text-3xl font-bold mb-2">Audit Logs</h2>
                  <p className="text-muted-foreground mb-6">
                    Monitor system activities and user actions
                  </p>
                  <AuditLogViewer />
                </div>
              </TabsContent>
            </Tabs>
          </div>
        </ProtectedRouteGuard>
      </div>
    </AppShell>
  );
}
