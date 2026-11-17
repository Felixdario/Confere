import { defineConfig, devices } from "@playwright/test";

/**
 * Fluxo principal contra a API real. Antes: `make up`, `make migrar`, `make seed`, `make dev-api` e
 * `make worker`. O Chrome instalado é usado (`channel: "chrome"`); nunca `playwright install`.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_URL ?? "http://localhost:3010",
    channel: "chrome",
    locale: "pt-BR",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "entrar", testMatch: /entrar.setup.ts/, use: { channel: "chrome" } },
    {
      name: "desktop",
      dependencies: ["entrar"],
      use: { ...devices["Desktop Chrome"], channel: "chrome", storageState: "e2e/.sessao/demo.json" },
    },
    {
      name: "celular",
      dependencies: ["entrar"],
      use: { ...devices["Pixel 7"], channel: "chrome", storageState: "e2e/.sessao/demo.json" },
    },
  ],
  webServer: {
    command: "corepack pnpm dev",
    url: "http://localhost:3010",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
