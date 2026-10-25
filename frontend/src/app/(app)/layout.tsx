import { Suspense } from "react";

import { AppNav, NavLinks } from "@/components/app-nav";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <>
      {/* The pathname is URL data on dynamic routes (/documents/[id]), so it streams in;
          the fallback is the same navigation with nothing marked current. */}
      <Suspense fallback={<NavLinks pathname={null} />}>
        <AppNav />
      </Suspense>
      <div className="flex flex-1 flex-col">{children}</div>
    </>
  );
}
