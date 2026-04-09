"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/hooks/use-auth";
import { useAuthStore } from "@/lib/stores/auth-store";
import { getConfig } from "@/lib/config";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  CardFooter,
} from "@/components/ui/card";
import { AlertCircle, Loader2, Github, Mail } from "lucide-react";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { useTranslation } from "@/lib/hooks/use-translation";
import Image from "next/image";

export function LoginForm() {
  const { t, language } = useTranslation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [oauthLoading, setOauthLoading] = useState<string | null>(null);
  const { isLoading: isPasswordLoading, error } = useAuth();
  const {
    authRequired,
    checkAuthRequired,
    hasHydrated,
    isAuthenticated,
    loginWithOAuth,
  } = useAuthStore();
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);
  const [configInfo, setConfigInfo] = useState<{
    apiUrl: string;
    version: string;
    buildTime: string;
  } | null>(null);
  const [loginMode, setLoginMode] = useState<"local" | "oauth">("oauth");
  const router = useRouter();

  // Load config info for debugging
  useEffect(() => {
    getConfig()
      .then((cfg) => {
        setConfigInfo({
          apiUrl: cfg.apiUrl,
          version: cfg.version,
          buildTime: cfg.buildTime,
        });
      })
      .catch((err) => {
        console.error("Failed to load config:", err);
      });
  }, []);

  // Check if authentication is required on mount
  useEffect(() => {
    if (!hasHydrated) {
      return;
    }

    const checkAuth = async () => {
      try {
        const required = await checkAuthRequired();

        // If auth is not required, redirect to notebooks
        if (!required) {
          router.push("/notebooks");
        }
      } catch (error) {
        console.error("Error checking auth requirement:", error);
        // On error, assume auth is required to be safe
      } finally {
        setIsCheckingAuth(false);
      }
    };

    // If user is already authenticated, redirect to notebooks immediately
    if (isAuthenticated) {
      router.push("/notebooks");
      return;
    }

    // If we already know auth status, use it
    if (authRequired !== null) {
      if (!authRequired) {
        router.push("/notebooks");
      } else {
        setIsCheckingAuth(false);
      }
    } else {
      void checkAuth();
    }
  }, [hasHydrated, authRequired, checkAuthRequired, router, isAuthenticated]);

  const handleOAuthLogin = async (provider: "azure" | "google" | "github") => {
    setOauthLoading(provider);
    try {
      const authUrl = await loginWithOAuth(provider);
      window.location.href = authUrl;
    } catch (error) {
      console.error(`OAuth login failed for ${provider}:`, error);
      setOauthLoading(null);
    }
  };

  const handleLocalLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password.trim()) {
      try {
        const { login } = useAuthStore.getState();
        await login(password);
      } catch (error) {
        console.error("Local login error:", error);
      }
    }
  };

  // Show loading while checking if auth is required
  if (!hasHydrated || isCheckingAuth) {
    return (
      <div className="min-h-dvh flex items-center justify-center bg-background">
        <LoadingSpinner />
      </div>
    );
  }

  // If we still don't know if auth is required (connection error), show error
  if (authRequired === null) {
    return (
      <div className="min-h-dvh flex items-center justify-center bg-background p-4">
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <CardTitle>{t.common.connectionError}</CardTitle>
            <CardDescription>{t.common.unableToConnect}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex items-start gap-2 text-red-600 text-sm">
                <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
                <div className="flex-1">
                  {error || "Unable to connect to API server"}
                </div>
              </div>

              {configInfo && (
                <div className="space-y-2 text-xs text-muted-foreground border-t pt-3">
                  <div className="font-medium">{t.common.diagnosticInfo}:</div>
                  <div className="space-y-1 font-mono">
                    <div>
                      {t.common.version}: {configInfo.version}
                    </div>
                    <div className="break-all">
                      {t.common.apiUrl}: {configInfo.apiUrl}
                    </div>
                  </div>
                </div>
              )}

              <Button
                onClick={() => window.location.reload()}
                className="w-full"
              >
                {t.common.retryConnection}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-dvh flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center space-y-3">
          <div className="flex justify-center">
            <Image
              src="/hero.png"
              alt="NNBook"
              width={192}
              height={192}
              style={{ width: 'auto', height: 'auto' }}
              priority
            />
          </div>
          <CardTitle className="text-2xl">NNBook</CardTitle>
        </CardHeader>

        <CardContent className="space-y-6">
          {/* OAuth Login Section */}
          {loginMode === "oauth" && (
            <div className="space-y-3">
              <div className="text-sm font-medium text-center text-muted-foreground">
                Sign in with
              </div>

              <Button
                onClick={() => handleOAuthLogin("azure")}
                disabled={oauthLoading !== null}
                variant="outline"
                className="w-full"
              >
                {oauthLoading === "azure" ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Redirecting...
                  </>
                ) : (
                  <>
                    <Mail className="h-4 w-4 mr-2" />
                    Azure AD
                  </>
                )}
              </Button>

              <Button
                onClick={() => handleOAuthLogin("google")}
                disabled={oauthLoading !== null}
                variant="outline"
                className="w-full"
              >
                {oauthLoading === "google" ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Redirecting...
                  </>
                ) : (
                  <>
                    <Mail className="h-4 w-4 mr-2" />
                    Google
                  </>
                )}
              </Button>

              <Button
                onClick={() => handleOAuthLogin("github")}
                disabled={oauthLoading !== null}
                variant="outline"
                className="w-full"
              >
                {oauthLoading === "github" ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Redirecting...
                  </>
                ) : (
                  <>
                    <Github className="h-4 w-4 mr-2" />
                    GitHub
                  </>
                )}
              </Button>

              <div className="relative">
                <div className="absolute inset-0 flex items-center">
                  <span className="w-full border-t" />
                </div>
                <div className="relative flex justify-center text-xs uppercase">
                  <span className="bg-background px-2 text-muted-foreground">
                    Or
                  </span>
                </div>
              </div>

              <Button
                onClick={() => setLoginMode("local")}
                variant="ghost"
                className="w-full"
              >
                Sign in with password
              </Button>

              {error && (
                <div className="flex items-start gap-2 text-red-600 text-sm">
                  <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}
            </div>
          )}

          {/* Local Login Section */}
          {loginMode === "local" && (
            <form onSubmit={handleLocalLogin} className="space-y-4">
              <div>
                <label className="text-sm font-medium">Email</label>
                <Input
                  type="email"
                  placeholder="admin@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={isPasswordLoading}
                />
              </div>

              <div>
                <label className="text-sm font-medium">Password</label>
                <Input
                  type="password"
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={isPasswordLoading}
                  autoFocus
                />
              </div>

              {error && (
                <div className="flex items-start gap-2 text-red-600 text-sm">
                  <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              <Button
                type="submit"
                className="w-full"
                disabled={isPasswordLoading || !password.trim()}
              >
                {isPasswordLoading ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Signing In...
                  </>
                ) : (
                  "Sign In"
                )}
              </Button>

              <Button
                type="button"
                onClick={() => setLoginMode("oauth")}
                variant="ghost"
                className="w-full"
              >
                Back to OAuth signin
              </Button>
            </form>
          )}
        </CardContent>

        {configInfo && (
          <CardFooter className="border-t text-xs text-muted-foreground text-center justify-center flex-col gap-1">
            <div>
              {t.common.version} {configInfo.version}
            </div>
            <div className="font-mono text-[10px] break-all">
              {configInfo.apiUrl}
            </div>
          </CardFooter>
        )}
      </Card>
    </div>
  );
}
