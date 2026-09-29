import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import "./globals.css";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import { LiveProvider } from "@/components/live-provider";
import { AppShell } from "@/components/app-shell";

const body = Inter({ variable: "--font-body", subsets: ["latin"] });
const display = Space_Grotesk({ variable: "--font-display", subsets: ["latin"], weight: ["500", "600", "700"] });
const code = JetBrains_Mono({ variable: "--font-code", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "GTA 7 Fuel Ops Console",
  description: "Fuel supply intelligence & resilience platform — operator console (simulated data)",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${body.variable} ${display.variable} ${code.variable} h-full antialiased`}>
      <body className="min-h-full bg-background font-sans text-foreground">
        <TooltipProvider>
          <LiveProvider>
            <AppShell>{children}</AppShell>
          </LiveProvider>
          <Toaster richColors position="bottom-right" />
        </TooltipProvider>
      </body>
    </html>
  );
}
