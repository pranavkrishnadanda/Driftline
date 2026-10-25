/** The views share the root layout's header; this group only stretches the page body. */
export default function AppLayout({ children }: LayoutProps<"/">) {
  return <div className="flex flex-1 flex-col">{children}</div>;
}
