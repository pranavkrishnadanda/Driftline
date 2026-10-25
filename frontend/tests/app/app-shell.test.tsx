import { render, screen, within } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import AppLayout from "@/app/(app)/layout";
import DriftPage from "@/app/(app)/drift/page";
import ReviewPage from "@/app/(app)/review/page";
import StatsPage from "@/app/(app)/stats/page";
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
    expect(within(nav).getByRole("link", { name: "Drift" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Ask" })).not.toHaveAttribute("aria-current");
  });

  it("treats nested paths as part of their view", () => {
    render(<NavLinks pathname="/timeline/abc" />);
    expect(screen.getByRole("link", { name: "Timeline" })).toHaveAttribute("aria-current", "page");
  });

  it("marks Timeline current on a document's timeline", () => {
    render(<NavLinks pathname="/documents/0b6f7e52-6a49-4d0e-9a3c-2f5d1c7e8a10" />);
    expect(screen.getByRole("link", { name: "Timeline" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Ask" })).not.toHaveAttribute("aria-current");
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

describe("built views", () => {
  it.each([
    ["Drift", DriftPage],
    ["Review", ReviewPage],
    ["Stats", StatsPage],
  ])("%s server-renders its heading, not the placeholder", (name, Page) => {
    const html = renderToStaticMarkup(<Page />);
    const doc = new DOMParser().parseFromString(html, "text/html");
    expect(doc.querySelector("h1")?.textContent).toBe(name);
    expect(doc.body.textContent).not.toMatch(/coming soon/i);
  });
});
