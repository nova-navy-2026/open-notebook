"use client";

import { useState, useEffect } from "react";
import { useAuthStore, UserRole } from "@/lib/stores/auth-store";
import { getApiUrl } from "@/lib/config";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { AlertCircle, Plus, Trash2, Edit2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface UserWithRoles {
  id: string;
  email: string;
  name?: string;
  roles: UserRole[];
  provider: "local" | "azure" | "google" | "github";
}

export function RoleManagementComponent() {
  const { token } = useAuthStore();
  const [users, setUsers] = useState<UserWithRoles[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<UserWithRoles | null>(null);
  const [selectedRole, setSelectedRole] = useState<UserRole>("viewer");
  const [searchQuery, setSearchQuery] = useState("");

  const filteredUsers = users.filter(
    (user) =>
      user.email.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (user.name &&
        user.name.toLowerCase().includes(searchQuery.toLowerCase())),
  );

  useEffect(() => {
    const fetchUsers = async () => {
      if (!token) return;

      try {
        setIsLoading(true);
        const apiUrl = await getApiUrl();

        const response = await fetch(`${apiUrl}/api/users`, {
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
        });

        if (!response.ok) {
          const statusText = response.statusText || "Unknown error";
          throw new Error(
            `Failed to fetch users: ${response.status} ${statusText}`,
          );
        }

        const data = await response.json();
        setUsers(Array.isArray(data) ? data : data.users || []);
        setError(null);
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : "Failed to fetch users";
        console.error("Users fetch error:", err);
        setError(errorMessage);
      } finally {
        setIsLoading(false);
      }
    };

    fetchUsers();
  }, [token]);

  const handleRoleChange = async (user: UserWithRoles, newRole: UserRole) => {
    if (!token) return;

    try {
      const apiUrl = await getApiUrl();

      const response = await fetch(`${apiUrl}/api/users/${user.id}/roles`, {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ roles: [newRole] }),
      });

      if (!response.ok) {
        const statusText = response.statusText || "Unknown error";
        throw new Error(
          `Failed to update user role: ${response.status} ${statusText}`,
        );
      }

      // Update local state
      setUsers(
        users.map((u) => (u.id === user.id ? { ...u, roles: [newRole] } : u)),
      );

      setDialogOpen(false);
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "Failed to update user role";
      console.error("Role update error:", err);
      alert(errorMessage);
    }
  };

  const handleDeleteUser = async (user: UserWithRoles) => {
    if (!token || !confirm(`Are you sure you want to delete ${user.email}?`))
      return;

    try {
      const apiUrl = await getApiUrl();

      const response = await fetch(`${apiUrl}/api/users/${user.id}`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        const statusText = response.statusText || "Unknown error";
        throw new Error(
          `Failed to delete user: ${response.status} ${statusText}`,
        );
      }

      // Update local state
      setUsers(users.filter((u) => u.id !== user.id));
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "Failed to delete user";
      console.error("User delete error:", err);
      alert(errorMessage);
    }
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>User Roles Management</CardTitle>
            <CardDescription>Manage user roles and permissions</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Search */}
        <div className="flex gap-2">
          <Input
            placeholder="Search users by email or name..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        {/* Users Table */}
        {error ? (
          <div className="flex items-start gap-2 text-red-600 text-sm">
            <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        ) : isLoading ? (
          <LoadingSpinner />
        ) : (
          <div className="border rounded-lg overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Email</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Roles</TableHead>
                  <TableHead>Provider</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredUsers.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className="text-center py-4 text-muted-foreground"
                    >
                      No users found
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredUsers.map((user) => (
                    <TableRow key={user.id}>
                      <TableCell className="font-medium">
                        {user.email}
                      </TableCell>
                      <TableCell>{user.name || "-"}</TableCell>
                      <TableCell>
                        <div className="flex gap-1">
                          {user.roles.map((role) => (
                            <Badge key={role} variant="secondary">
                              {role.charAt(0).toUpperCase() + role.slice(1)}
                            </Badge>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell className="capitalize">
                        {user.provider}
                      </TableCell>
                      <TableCell className="text-right space-x-2">
                        <Dialog
                          open={selectedUser?.id === user.id && dialogOpen}
                          onOpenChange={(open) => {
                            setDialogOpen(open);
                            if (!open) setSelectedUser(null);
                          }}
                        >
                          <DialogTrigger asChild>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => {
                                setSelectedUser(user);
                                setSelectedRole(user.roles[0]);
                                setDialogOpen(true);
                              }}
                            >
                              <Edit2 className="h-4 w-4" />
                            </Button>
                          </DialogTrigger>
                          {selectedUser?.id === user.id && (
                            <DialogContent>
                              <DialogHeader>
                                <DialogTitle>Change User Role</DialogTitle>
                                <DialogDescription>
                                  Update role for {user.email}
                                </DialogDescription>
                              </DialogHeader>
                              <div className="space-y-4">
                                <div>
                                  <label className="text-sm font-medium">
                                    Role
                                  </label>
                                  <Select
                                    value={selectedRole}
                                    onValueChange={(v) =>
                                      setSelectedRole(v as UserRole)
                                    }
                                  >
                                    <SelectTrigger>
                                      <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                      <SelectItem value="admin">
                                        Admin
                                      </SelectItem>
                                      <SelectItem value="editor">
                                        Editor
                                      </SelectItem>
                                      <SelectItem value="viewer">
                                        Viewer
                                      </SelectItem>
                                    </SelectContent>
                                  </Select>
                                </div>
                                <div className="flex gap-2 justify-end">
                                  <Button
                                    variant="outline"
                                    onClick={() => setDialogOpen(false)}
                                  >
                                    Cancel
                                  </Button>
                                  <Button
                                    onClick={() =>
                                      handleRoleChange(user, selectedRole)
                                    }
                                  >
                                    Save Changes
                                  </Button>
                                </div>
                              </div>
                            </DialogContent>
                          )}
                        </Dialog>

                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => handleDeleteUser(user)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
