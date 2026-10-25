import { render, screen, within } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import AppLayout from "@/app/(app)/layout";
import DriftPage from "@/app/(app)/drift/page";
import ReviewPage from "@/app/(app)/review/page";
import StatsPage from "@/app/(app)/stats/page";
import TimelinePage from "@/app/(app)/timeline/page";
import { NAV_ITEMS, NavLinks } from "@/components/app-nav";

describe("app shell navigation", () => {
  it("links every view: Ask, Timeline, Drift, Review and Stats", () => {
    expect(NAV_ITEMS.map((item) => [item.label, item.href])).toEqual([
      ["Ask", "/ask"],
      ["Timeline", "/timeline"],
      ["Drift", "/drift"],
      ["Review", "/review"],
      ["Stats", "/stats"],
    ]);
  });

  it("marks the current view for assistive technology", () => {
    render(<NavLinks pathname="/drift" />);
    const nav = screen.getByRole("navigation", { name: "Views" });
    const links = within(nav).getAllByRole("link");
    expect(links).toHaveLength(5);
    expect(within(nav).getByRole("link", { name: "Drift" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Ask" })).not.toHaveAttribute("aria-current");
  });

  it("treats nested paths as part of their view", () => {
    render(<NavLinks pathname="/timeline/abc" />);
    expect(screen.getByRole("link", { name: "Timeline" })).toHaveAttribute("aria-current", "page");
  });

  it("renders the navigation around the page", () => {
    const html = renderToStaticMarkup(
      <AppLayout params={Promise.resolve({})}>
        <p>page body</p>
      </AppLayout>,
    );
    const doc = new DOMParser().parseFromString(html, "text/html");
    const hrefs = [...doc.querySelectorAll("nav[aria-label='Views'] a")].map((a) =>
      a.getAttribute("href"),
    );
    expect(hrefs).toEqual(["/ask", "/timeline", "/drift", "/review", "/stats"]);
    expect(doc.body.textContent).toContain("page body");
  });
});

describe("views that are not built yet", () => {
  it.each([
    ["Timeline", TimelinePage],
    ["Drift", DriftPage],
    ["Review", ReviewPage],
    ["Stats", StatsPage],
  ])("%s renders a coming-soon placeholder instead of a 404", (name, Page) => {
    render(<Page />);
    expect(screen.getByRole("heading", { level: 1, name })).toBeInTheDocument();
    expect(screen.getByText(/coming soon/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ask a question/ })).toHaveAttribute("href", "/ask");
  });
});
