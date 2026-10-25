"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useLayoutEffect, useRef } from "react";

import { cn } from "@/lib/utils";

export const NAV_ITEMS = [
  { href: "/ask", label: "Ask" },
  // A document's timeline (/documents/<id>) is reached from the Timeline picker.
  { href: "/timeline", label: "Timeline", also: ["/documents"] },
  { href: "/drift", label: "Drift" },
  { href: "/review", label: "Review" },
  { href: "/stats", label: "Stats" },
] as const;

type NavItem = (typeof NAV_ITEMS)[number];

function isUnder(pathname: string | null, href: string): boolean {
  return pathname === href || (pathname?.startsWith(`${href}/`) ?? false);
}

export function isCurrent(pathname: string | null, item: NavItem): boolean {
  const also: readonly string[] = "also" in item ? item.also : [];
  return isUnder(pathname, item.href) || also.some((href) => isUnder(pathname, href));
}

export interface NavLinksProps {
  /**
   * The current path, to mark the current view. Leave it out to have each link read the
   * URL itself (in the header): the links then prerender, and only the marker streams in.
   */
  pathname?: string | null;
  /** A row in the header, or a column in the mobile menu. */
  orientation?: "horizontal" | "vertical";
  /** Called when a link is followed (the mobile menu closes itself). */
  onNavigate?: () => void;
  className?: string;
}

const DOT = "rounded-full bg-brand";

/**
 * Marks its link as the current page once the URL is known. The pathname is URL data
 * on dynamic routes (/documents/[id]), so this small leaf sits in its own Suspense
 * boundary and the link itself stays in the prerendered shell.
 */
function CurrentMarker({ item, vertical }: { item: NavItem; vertical: boolean }) {
  const current = isCurrent(usePathname(), item);
  const ref = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const link = ref.current?.closest("a");
    if (!link) return;
    if (current) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }, [current]);
  return (
    <span
      ref={ref}
      aria-hidden="true"
      className={cn(current ? DOT : "hidden", vertical ? "mr-3 size-2" : "mr-1.5 size-1.5")}
    />
  );
}

export function NavLinks({
  pathname,
  orientation = "horizontal",
  onNavigate,
  className,
}: NavLinksProps) {
  const vertical = orientation === "vertical";
  const known = pathname !== undefined;
  return (
    <nav aria-label="Views" className={className}>
      <ul className={cn("flex gap-1", vertical ? "flex-col" : "items-center")}>
        {NAV_ITEMS.map((item) => {
          const current = known && isCurrent(pathname, item);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={current ? "page" : undefined}
                onClick={onNavigate}
                className={cn(
                  "relative inline-flex items-center rounded-full font-medium transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                  vertical ? "h-11 w-full px-4 text-base" : "h-8 px-3 text-sm",
                  "text-muted-foreground hover:bg-muted hover:text-foreground",
                  "aria-[current=page]:bg-brand-soft aria-[current=page]:text-foreground",
                )}
              >
                {known ? (
                  current ? (
                    <span
                      aria-hidden="true"
                      className={cn(DOT, vertical ? "mr-3 size-2" : "mr-1.5 size-1.5")}
                    />
                  ) : null
                ) : (
                  <Suspense fallback={null}>
                    <CurrentMarker item={item} vertical={vertical} />
                  </Suspense>
                )}
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** The navigation reading the current view from the URL. */
export function AppNav(props: Omit<NavLinksProps, "pathname">) {
  return <NavLinks {...props} />;
}
