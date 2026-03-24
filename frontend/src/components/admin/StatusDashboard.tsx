"use client";

import { useState, useEffect } from "react";
import { apiClient } from "@/lib/api/client";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  RefreshCw,
  CheckCircle,
  AlertCircle,
  XCircle,
  Loader2,
} from "lucide-react";

interface ServiceStatus {
  name: string;
  status: "healthy" | "degraded" | "offline";
  responseTime?: number;
  message?: string;
}

interface HealthData {
  api: ServiceStatus;
  database: ServiceStatus;
  auth: ServiceStatus;
  timestamp: Date;
}

export function StatusDashboard() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const checkHealth = async () => {
    try {
      setIsLoading(true);
      const startTime = Date.now();

      // Check API health
      const apiResponse = await apiClient.get("/health").catch(() => null);
      const apiTime = Date.now() - startTime;
      const apiHealthy = !!apiResponse;

      // Try to get system info (this also validates auth)
      const authResponse = await apiClient.get("/auth/me").catch(() => null);
      const authHealthy = !!authResponse;

      // Try database health (if available)
      const dbResponse = await apiClient.get("/health/db").catch(() => null);
      const dbHealthy = !!dbResponse;

      setHealth({
        api: {
          name: "API Server",
          status: apiHealthy ? "healthy" : "offline",
          responseTime: apiTime,
          message: apiHealthy
            ? `${apiTime}ms response time`
            : "API not responding",
        },
        database: {
          name: "Database",
          status: dbHealthy ? "healthy" : "offline",
          message: dbHealthy ? "Connected" : "Connection failed",
        },
        auth: {
          name: "Authentication",
          status: authHealthy ? "healthy" : "degraded",
          message: authHealthy ? "Active" : "Issues detected",
        },
        timestamp: new Date(),
      });

      setLastRefresh(new Date());
    } catch (err) {
      console.error("Health check error:", err);
      setHealth({
        api: {
          name: "API Server",
          status: "offline",
          message: err instanceof Error ? err.message : "Unknown error",
        },
        database: {
          name: "Database",
          status: "offline",
          message: "Unable to verify",
        },
        auth: {
          name: "Authentication",
          status: "offline",
          message: "Unable to verify",
        },
        timestamp: new Date(),
      });
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    checkHealth();
    if (!autoRefresh) return;

    const interval = setInterval(() => {
      checkHealth();
    }, 30000); // Refresh every 30 seconds

    return () => clearInterval(interval);
  }, [autoRefresh]);

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "healthy":
        return <CheckCircle className="h-5 w-5 text-green-600" />;
      case "degraded":
        return <AlertCircle className="h-5 w-5 text-yellow-600" />;
      case "offline":
        return <XCircle className="h-5 w-5 text-red-600" />;
      default:
        return null;
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "healthy":
        return <Badge className="bg-green-600">Healthy</Badge>;
      case "degraded":
        return <Badge className="bg-yellow-600">Degraded</Badge>;
      case "offline":
        return <Badge className="bg-red-600">Offline</Badge>;
      default:
        return null;
    }
  };

  const overallStatus = !health
    ? "offline"
    : health.api.status === "offline" || health.database.status === "offline"
      ? "offline"
      : health.api.status === "degraded" ||
          health.database.status === "degraded" ||
          health.auth.status === "degraded"
        ? "degraded"
        : "healthy";

  return (
    <div className="space-y-4">
      {/* Overall Status */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>System Status</CardTitle>
              <CardDescription>
                Real-time health check of system components
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={checkHealth}
                disabled={isLoading}
              >
                {isLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
              </Button>
              <Button
                size="sm"
                variant={autoRefresh ? "default" : "outline"}
                onClick={() => setAutoRefresh(!autoRefresh)}
              >
                {autoRefresh ? "Auto-On" : "Auto-Off"}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between p-4 border rounded-lg bg-muted/50">
            <div className="flex items-center gap-3">
              {getStatusIcon(overallStatus)}
              <div>
                <p className="font-semibold">Overall Status</p>
                <p className="text-sm text-muted-foreground">
                  {lastRefresh &&
                    `Last checked: ${lastRefresh.toLocaleTimeString()}`}
                </p>
              </div>
            </div>
            {getStatusBadge(overallStatus)}
          </div>

          {/* Service Status Grid */}
          <div className="grid md:grid-cols-3 gap-3">
            {health &&
              [health.api, health.database, health.auth].map((service) => (
                <div
                  key={service.name}
                  className="p-4 border rounded-lg space-y-2"
                >
                  <div className="flex items-center justify-between">
                    <h4 className="font-medium text-sm">{service.name}</h4>
                    {getStatusIcon(service.status)}
                  </div>
                  <div className="space-y-1">
                    <p className="text-sm text-muted-foreground">
                      {service.message}
                    </p>
                    {service.responseTime && (
                      <p className="text-xs text-muted-foreground font-mono">
                        {service.responseTime}ms
                      </p>
                    )}
                  </div>
                </div>
              ))}
          </div>
        </CardContent>
      </Card>

      {/* Detailed Status Metrics */}
      <Card>
        <CardHeader>
          <CardTitle>System Metrics</CardTitle>
          <CardDescription>
            Detailed performance and availability information
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid md:grid-cols-2 gap-4">
            {health &&
              [
                {
                  label: "API Response Time",
                  value: health.api.responseTime
                    ? `${health.api.responseTime}ms`
                    : "N/A",
                  status:
                    health.api.responseTime && health.api.responseTime < 500
                      ? "good"
                      : health.api.responseTime &&
                          health.api.responseTime < 1000
                        ? "ok"
                        : "slow",
                },
                {
                  label: "Database Connection",
                  value:
                    health.database.status === "healthy"
                      ? "Connected"
                      : "Disconnected",
                  status: health.database.status === "healthy" ? "good" : "bad",
                },
                {
                  label: "Authentication Service",
                  value: health.auth.status === "healthy" ? "Active" : "Issues",
                  status: health.auth.status === "healthy" ? "good" : "bad",
                },
                {
                  label: "Last Check",
                  value: health.timestamp.toLocaleTimeString(),
                  status: "neutral",
                },
              ].map((metric, i) => (
                <div key={i} className="space-y-1 p-3 border rounded">
                  <p className="text-sm text-muted-foreground">
                    {metric.label}
                  </p>
                  <p className="font-medium">{metric.value}</p>
                </div>
              ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
