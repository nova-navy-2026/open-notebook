"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { MapPin, Loader2, ArrowRight, Route } from "lucide-react";
import { getApiUrl } from "@/lib/config";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useTranslation } from "@/lib/hooks/use-translation";

interface NavPoint {
  query: string;
  resolved_address: string;
  lat: number;
  lon: number;
}

interface NavResult {
  start_point: NavPoint;
  end_point: NavPoint;
  distance_km: number;
  estimated_time: string;
  route_preference: string;
  source: string;
}

export default function NavigationPage() {
  const { t } = useTranslation();
  const tp = t.routePlannerPage;
  const [locationA, setLocationA] = useState("");
  const [locationB, setLocationB] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<NavResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!locationA.trim() || !locationB.trim()) {
      setError("Please provide both an origin and a destination.");
      return;
    }

    setIsLoading(true);
    setError(null);
    setResult(null);

    try {
      const apiUrl = await getApiUrl();
      const token = useAuthStore.getState().token;
      const response = await fetch(`${apiUrl}/api/navigation/route`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          location_a: locationA.trim(),
          location_b: locationB.trim(),
        }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => null);
        throw new Error(err?.detail || `Server error (${response.status})`);
      }

      const data: NavResult = await response.json();
      setResult(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to compute route.";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  const mapUrl = result
    ? `https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route=${result.start_point.lat}%2C${result.start_point.lon}%3B${result.end_point.lat}%2C${result.end_point.lon}`
    : null;

  return (
    <div className="flex flex-col h-full overflow-y-auto px-4 md:px-6 py-6 space-y-6">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold tracking-tight">{tp.title}</h1>
        <p className="text-muted-foreground">
          {tp.subtitle}
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6 max-w-2xl">
        <div className="space-y-2">
          <Label htmlFor="locA">{tp.origin}</Label>
          <Input
            id="locA"
            type="text"
            value={locationA}
            onChange={(e) => setLocationA(e.target.value)}
            placeholder={tp.originPlaceholder}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="locB">{tp.destination}</Label>
          <Input
            id="locB"
            type="text"
            value={locationB}
            onChange={(e) => setLocationB(e.target.value)}
            placeholder={tp.destinationPlaceholder}
          />
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Button
          type="submit"
          disabled={isLoading || !locationA.trim() || !locationB.trim()}
        >
          {isLoading ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              {tp.computing}
            </>
          ) : (
            <>
              <Route className="h-4 w-4 mr-2" />
              {tp.compute}
            </>
          )}
        </Button>
      </form>

      {result && (
        <div className="space-y-4 max-w-3xl">
          <h2 className="text-xl font-semibold tracking-tight">Result</h2>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Route className="h-4 w-4" />
                {result.distance_km} km &mdash; {result.estimated_time}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <p className="text-muted-foreground">
                {result.route_preference}
              </p>

              <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr] gap-3 items-center">
                <div className="space-y-1">
                  <div className="flex items-center gap-2 font-medium">
                    <MapPin className="h-4 w-4 text-green-600" />
                    {result.start_point.query}
                  </div>
                  <p className="text-xs text-muted-foreground pl-6">
                    {result.start_point.resolved_address}
                  </p>
                  <p className="text-xs text-muted-foreground pl-6 font-mono">
                    {result.start_point.lat.toFixed(5)},{" "}
                    {result.start_point.lon.toFixed(5)}
                  </p>
                </div>
                <ArrowRight className="h-5 w-5 text-muted-foreground hidden md:block mx-auto" />
                <div className="space-y-1">
                  <div className="flex items-center gap-2 font-medium">
                    <MapPin className="h-4 w-4 text-red-600" />
                    {result.end_point.query}
                  </div>
                  <p className="text-xs text-muted-foreground pl-6">
                    {result.end_point.resolved_address}
                  </p>
                  <p className="text-xs text-muted-foreground pl-6 font-mono">
                    {result.end_point.lat.toFixed(5)},{" "}
                    {result.end_point.lon.toFixed(5)}
                  </p>
                </div>
              </div>

              {mapUrl && (
                <div className="pt-2">
                  <a
                    href={mapUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary text-sm hover:underline"
                  >
                    {tp.openInMaps} →
                  </a>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
