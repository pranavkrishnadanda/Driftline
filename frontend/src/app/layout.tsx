import type { Metadata } from "next";
import Link from "next/link";

import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Driftline",
  description: "Point-in-time answers over versioned documents, with live drift alerts.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col bg-background text-foreground">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:ring-2 focus:ring-ring"
        >
          Skip to content
        </a>
        <header className="border-b border-border">
          <div className="mx-auto flex h-14 w-full max-w-6xl items-center px-4">
            <Link href="/" className="font-heading text-lg font-semibold tracking-tight">
              Driftline
            </Link>
          </div>
        </header>
        <Providers>
          <main id="main" className="flex flex-1 flex-col">
            {children}
          </main>
        </Providers>
      </body>
    </html>
  );
}
