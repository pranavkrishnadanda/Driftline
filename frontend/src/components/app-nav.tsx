"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

export const NAV_ITEMS = [
  { href: "/ask", label: "Ask" },
  // A document's timeline (/documents/<id>) is reached from the Timeline picker.
  { href: "/timeline", label: "Timeline", also: ["/documents"] },
  { href: "/drift", label: "Drift" },
  { href: "/review", label: "Review" },
  { href: "/stats", label: "Stats" },
] as const;

function isUnder(pathname: string | null, href: string): boolean {
  return pathname === href || (pathname?.startsWith(`${href}/`) ?? false);
}

function isCurrent(pathname: string | null, item: (typeof NAV_ITEMS)[number]): boolean {
  const also: readonly string[] = "also" in item ? item.also : [];
  return isUnder(pathname, item.href) || also.some((href) => isUnder(pathname, href));
}

export function NavLinks({ pathname }: { pathname: string | null }) {
  return (
    <nav aria-label="Views" className="border-b border-border">
      <ul className="mx-auto flex w-full max-w-6xl gap-1 overflow-x-auto px-4 py-2">
        {NAV_ITEMS.map((item) => {
          const current = isCurrent(pathname, item);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={current ? "page" : undefined}
                className={cn(
                  "inline-flex h-8 items-center rounded-md px-3 text-sm font-medium",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                  current
                    ? "bg-secondary text-secondary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export function AppNav() {
  return <NavLinks pathname={usePathname()} />;
}
