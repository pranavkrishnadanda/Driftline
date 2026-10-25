import type { Metadata } from "next";

import { SiteHeader } from "@/components/site-header";
import { THEME_SCRIPT } from "@/components/theme-toggle";

import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Driftline",
  description: "Point-in-time answers over versioned documents, with live drift alerts.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // The theme script sets `dark` on <html> before React hydrates.
    <html lang="en" className="h-full antialiased" suppressHydrationWarning>
      <head>
        {/* A constant script (no input): picks light or dark before the first paint. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="flex min-h-full flex-col bg-background text-foreground">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:ring-2 focus:ring-ring"
        >
          Skip to content
        </a>
        <SiteHeader />
        <Providers>
          <main id="main" className="flex flex-1 flex-col">
            {children}
          </main>
        </Providers>
      </body>
    </html>
  );
}
