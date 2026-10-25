/**
 * Demo build only (next.config.ts aliases `@/lib/api/client` here): the real module's
 * types and helpers, with `createApiClient` answering from the recording.
 */
import { createDemoClient } from "../lib/demo/client";
import type { ApiClient, ApiClientOptions } from "../lib/api/client";

export * from "../lib/api/client";

export function createApiClient(_options: ApiClientOptions = {}): ApiClient {
  return createDemoClient();
}
