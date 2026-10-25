import { AppNav } from "@/components/app-nav";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <>
      <AppNav />
      <div className="flex flex-1 flex-col">{children}</div>
    </>
  );
}
