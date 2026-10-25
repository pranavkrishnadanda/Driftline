/**
 * Demo build only (next.config.ts aliases `@/components/site-header` here): the recorded
 * demo banner above the normal header, on every page.
 */
import { DemoBanner } from "../components/demo/demo-banner";
import { SiteHeader as BaseSiteHeader } from "../components/site-header";

export function SiteHeader() {
  return (
    <>
      <DemoBanner />
      <BaseSiteHeader />
    </>
  );
}
