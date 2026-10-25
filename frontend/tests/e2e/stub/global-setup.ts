/**
 * Starts the stub gateway (tests/support/stub-gateway.ts) for `playwright.stub.config.ts`
 * and stops it after the run.
 */
import { startStubGateway } from "../../support/stub-gateway";

export const STUB_GATEWAY_PORT = Number(process.env.STUB_GATEWAY_PORT ?? 8019);

export default async function globalSetup(): Promise<() => Promise<void>> {
  const gateway = await startStubGateway({ port: STUB_GATEWAY_PORT });
  return () => gateway.close();
}
