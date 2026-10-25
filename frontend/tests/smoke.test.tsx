import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import RootLayout, { metadata } from "@/app/layout";

function renderLayout(): Document {
  const html = renderToStaticMarkup(
    <RootLayout params={Promise.resolve({})}>
      <p>child content</p>
    </RootLayout>,
  );
  return new DOMParser().parseFromString(html, "text/html");
}

describe("root layout", () => {
  it("renders the app name", () => {
    const doc = renderLayout();
    const brand = doc.querySelector("header a[href='/']");
    expect(brand?.textContent).toBe("Driftline");
    expect(metadata.title).toBe("Driftline");
  });

  it("renders its children inside the main landmark", () => {
    const doc = renderLayout();
    expect(doc.documentElement.getAttribute("lang")).toBe("en");
    expect(doc.querySelector("main#main")?.textContent).toContain("child content");
  });

  it("offers a keyboard skip link to the main content", () => {
    const doc = renderLayout();
    const skip = doc.querySelector("a[href='#main']");
    expect(skip?.textContent).toBe("Skip to content");
  });
});
