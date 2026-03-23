"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore } from "@/lib/stores/auth-store";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { AlertCircle } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export default function OAuthCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { handleOAuthCallback } = useAuthStore();
  const [error, setError] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(true);

  useEffect(() => {
    const processCallback = async () => {
      try {
        // Extract OAuth parameters from URL
        const code = searchParams.get("code");
        const state = searchParams.get("state");
        const provider = (searchParams.get("provider") || "azure") as
          | "azure"
          | "google"
          | "github";

        if (!code) {
          const errorCode = searchParams.get("error");
          const errorDesc = searchParams.get("error_description");
          throw new Error(
            `OAuth failed: ${errorCode} - ${errorDesc || "Unknown error"}`,
          );
        }

        if (!state) {
          throw new Error(
            "OAuth state validation failed: missing state parameter",
          );
        }

        // Handle the OAuth callback
        const success = await handleOAuthCallback(code, state, provider);

        if (success) {
          // Redirect to dashboard
          router.push("/notebooks");
        } else {
          setError("Authentication failed. Please try again.");
          setIsProcessing(false);
        }
      } catch (err) {
        const errorMessage =
          err instanceof Error
            ? err.message
            : "An error occurred during OAuth callback";
        console.error("OAuth callback error:", err);
        setError(errorMessage);
        setIsProcessing(false);
      }
    };

    // Only process if we're ready
    if (searchParams) {
      processCallback();
    }
  }, [searchParams, handleOAuthCallback, router]);

  if (isProcessing) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-center space-y-4">
          <LoadingSpinner />
          <p className="text-sm text-muted-foreground">
            Processing OAuth callback...
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <CardTitle>Authentication Failed</CardTitle>
            <CardDescription>
              There was a problem completing your login
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-start gap-2 text-red-600 text-sm">
              <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
              <span>{error}</span>
            </div>
            <Button onClick={() => router.push("/login")} className="w-full">
              Back to Login
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return null;
}
