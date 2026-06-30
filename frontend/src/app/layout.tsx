import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/sonner";
import { QueryProvider } from "@/components/providers/QueryProvider";
import { ThemeProvider } from "@/components/providers/ThemeProvider";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";
import { ConnectionGuard } from "@/components/common/ConnectionGuard";
import { SuppressHydrationWarning } from "@/components/common/SuppressHydrationWarning";
import { I18nProvider } from "@/components/providers/I18nProvider";
import { RBACProvider } from "@/lib/contexts/rbac-context";
import { TooltipProvider } from "@/components/ui/tooltip";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Marinheiro de Silício",
  description: "Privacy-focused research and knowledge management",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full" suppressHydrationWarning>
      <body className={`${inter.className} h-full`} suppressHydrationWarning>
        <SuppressHydrationWarning />
        <ErrorBoundary>
          <ThemeProvider>
            <QueryProvider>
              <I18nProvider>
                {/* App-wide tooltip provider so every button gets the same
                    instant, styled hover popup (delayDuration=0 matches the
                    sidebar theme/language buttons). */}
                <TooltipProvider delayDuration={0}>
                  <RBACProvider>
                    <ConnectionGuard>
                      {children}
                      <Toaster />
                    </ConnectionGuard>
                  </RBACProvider>
                </TooltipProvider>
              </I18nProvider>
            </QueryProvider>
          </ThemeProvider>
        </ErrorBoundary>
      </body>
    </html>
  );
}
