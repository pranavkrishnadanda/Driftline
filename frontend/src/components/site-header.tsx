import Link from "next/link";

import { AppNav } from "@/components/app-nav";
import { MobileMenu } from "@/components/mobile-menu";
import { ThemeToggle } from "@/components/theme-toggle";
import { buttonVariants } from "@/components/ui/button";
import { parseTenants } from "@/lib/ask/format";
import { cn } from "@/lib/utils";

/** Three versions of a line, the newest in force: Driftline's mark. */
function LogoMark() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-7 shrink-0">
      <rect width="24" height="24" rx="7" className="fill-brand" />
      <path
        d="M5 15.5c2.5 0 3-4 5.5-4s3 3 5.5 3 2.5-5 3-6"
        fill="none"
        strokeWidth="2"
        strokeLinecap="round"
        className="stroke-brand-foreground"
      />
      <circle cx="19" cy="8.5" r="1.8" className="fill-brand-foreground" />
    </svg>
  );
}

/**
 * The header on every page: the wordmark, the five views, the theme switch and the main
 * call to action. Sticky, with a hairline border and a blur over scrolled content. On
 * small screens the views move into an accessible menu (`MobileMenu`).
 */
export function SiteHeader() {
  const tenants = parseTenants(process.env.NEXT_PUBLIC_DRIFTLINE_TENANTS);
  // One workspace: say which. Several: each view has its own picker.
  const tenant = tenants.length === 1 ? tenants[0] : null;
  return (
    <header className="sticky top-0 z-40 border-b border-border/70 bg-background/80 backdrop-blur-md supports-[backdrop-filter]:bg-background/70">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-4 px-4">
        <Link
          href="/"
          className="flex items-center gap-2 rounded-md font-heading text-lg font-semibold tracking-tight focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          <LogoMark />
          <span>Driftline</span>
        </Link>

        {/* The links prerender; only the current-view marker reads the URL. */}
        <AppNav className="hidden md:block" />

        <div className="ml-auto flex items-center gap-1.5">
          {tenant ? (
            <span
              title="The workspace your questions and documents belong to"
              className="mr-1 hidden items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground lg:inline-flex"
            >
              <span aria-hidden="true" className="size-1.5 rounded-full bg-valid" />
              Workspace <span className="font-medium text-foreground">{tenant}</span>
            </span>
          ) : null}
          <ThemeToggle className="hidden md:inline-flex" />
          <Link
            href="/ask"
            className={cn(
              buttonVariants({ size: "lg" }),
              "hidden rounded-full px-4 shadow-sm sm:inline-flex",
            )}
          >
            Try Ask
          </Link>
          <MobileMenu tenant={tenant} />
        </div>
      </div>
    </header>
  );
}
