"use client";

import { Dialog } from "@base-ui/react/dialog";
import { Menu, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AppNav } from "@/components/app-nav";
import { ThemeToggle } from "@/components/theme-toggle";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * The header's navigation on small screens: a Base UI dialog (the primitive under
 * shadcn's Sheet), so focus is trapped inside while it is open, Escape closes it, and
 * focus returns to the menu button.
 */
export function MobileMenu({ tenant }: { tenant: string | null }) {
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger
        aria-label="Open menu"
        className={cn(
          "inline-flex size-9 items-center justify-center rounded-full text-foreground hover:bg-muted md:hidden",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        )}
      >
        <Menu aria-hidden="true" className="size-5" />
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-50 bg-black/30 backdrop-blur-[2px] transition-opacity duration-200 data-[ending-style]:opacity-0 data-[starting-style]:opacity-0 motion-reduce:transition-none" />
        <Dialog.Popup
          className={cn(
            "fixed inset-x-0 top-0 z-50 flex flex-col gap-4 rounded-b-2xl border-b bg-background px-4 pt-3 pb-6 shadow-lg outline-none",
            "transition-transform duration-200 data-[ending-style]:-translate-y-4 data-[starting-style]:-translate-y-4 motion-reduce:transition-none",
          )}
        >
          <div className="flex h-10 items-center justify-between">
            <Dialog.Title className="font-heading text-base font-semibold">Menu</Dialog.Title>
            <Dialog.Close
              aria-label="Close menu"
              className="inline-flex size-9 items-center justify-center rounded-full hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X aria-hidden="true" className="size-5" />
            </Dialog.Close>
          </div>
          <AppNav orientation="vertical" onNavigate={close} />
          <div className="flex items-center justify-between gap-3 border-t pt-4">
            {tenant ? (
              <span className="text-sm text-muted-foreground">
                Workspace <span className="font-medium text-foreground">{tenant}</span>
              </span>
            ) : (
              <span />
            )}
            <ThemeToggle />
          </div>
          <Link
            href="/ask"
            onClick={close}
            className={cn(buttonVariants({ size: "lg" }), "h-11 w-full rounded-full text-base")}
          >
            Try Ask
          </Link>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
