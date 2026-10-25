/**
 * The recorded demo (GitHub Pages) build switch.
 *
 * `NEXT_PUBLIC_DRIFTLINE_DEMO=1` at build time makes the API client and `useEventStream`
 * read a recording of a real run (`public/demo/recording.json`) instead of the network.
 * next.config.ts always defines the flag, so a normal build inlines `false` here and the
 * minifier drops every demo branch.
 */
export const DEMO = process.env.NEXT_PUBLIC_DRIFTLINE_DEMO === "1";

/** The static export's base path (next.config.ts `basePath`), e.g. `/Driftline/demo`. */
export const DEMO_BASE_PATH = process.env.DRIFTLINE_DEMO_BASE_PATH ?? "";

/** When the recording was captured (ISO), inlined from the recording at build time. */
export const DEMO_RECORDED_AT = process.env.DRIFTLINE_DEMO_RECORDED_AT ?? "";

/** The recording, served from `public/` next to the export. */
export const DEMO_RECORDING_FILE = "/demo/recording.json";

/**
 * The gateway origin the demo client reports. Not fetchable on purpose: every URL built
 * from it is answered from the recording.
 */
export const DEMO_API_BASE = "demo://recorded";

/** Where a visitor learns to run the real stack. */
export const QUICK_START_URL = "https://github.com/pranavkrishnadanda/Driftline#quick-start";
