"use client";

import { User } from "lucide-react";
import { useAuthStore } from "@/lib/stores/auth-store";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";

// Read-only profile page. There is no backend endpoint to edit a user profile
// yet, so this surfaces the account details already held in the auth store.
// Labels are hardcoded English to match the (also hardcoded) UserProfileMenu.
export default function ProfileSettingsPage() {
  const { user } = useAuthStore();

  const initials = user?.name
    ? user.name
        .split(" ")
        .map((n) => n[0])
        .join("")
        .toUpperCase()
    : (user?.email?.[0] || "U").toUpperCase();

  const providerLabel =
    user?.provider === "azure"
      ? "Microsoft (Azure)"
      : user?.provider === "local"
        ? "Local"
        : null;

  return (
    <div className="w-full h-full flex flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto">
        <div className="app-page">
          <div className="space-y-6">
            <div className="flex items-center gap-3 mb-2">
              <User className="h-6 w-6" />
              <h1 className="text-2xl sm:text-3xl font-bold">Profile Settings</h1>
            </div>

            {!user ? (
              <p className="text-muted-foreground">Loading...</p>
            ) : (
              <Card className="max-w-2xl">
                <CardHeader>
                  <CardTitle className="flex items-center gap-3">
                    <Avatar className="h-12 w-12">
                      {user.avatar && (
                        <AvatarImage
                          src={user.avatar}
                          alt={user.name || user.email}
                        />
                      )}
                      <AvatarFallback>{initials}</AvatarFallback>
                    </Avatar>
                    <span>{user.name || user.email}</span>
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <ProfileRow label="Name" value={user.name || "—"} />
                  <ProfileRow label="Email" value={user.email} />
                  <div className="flex flex-col gap-1">
                    <span className="text-sm text-muted-foreground">Roles</span>
                    <div className="flex flex-wrap gap-2">
                      {user.roles.length > 0 ? (
                        user.roles.map((role) => (
                          <Badge key={role} variant="secondary">
                            {role.charAt(0).toUpperCase() + role.slice(1)}
                          </Badge>
                        ))
                      ) : (
                        <span className="text-sm">—</span>
                      )}
                    </div>
                  </div>
                  {providerLabel && (
                    <ProfileRow label="Sign-in method" value={providerLabel} />
                  )}
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ProfileRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-sm font-medium break-words">{value}</span>
    </div>
  );
}
