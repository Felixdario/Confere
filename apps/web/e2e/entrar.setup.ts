import { existsSync } from "node:fs";

import { expect, request, test as setup } from "@playwright/test";

export const SESSAO = "e2e/.sessao/demo.json";

// Entra uma vez na conta de demonstração e guarda a sessão. A API limita 5 logins a cada 15 min por
// e-mail, então uma sessão salva que ainda vale é reaproveitada.
setup("entrar na demonstração", async ({ page, baseURL }) => {
  if (existsSync(SESSAO)) {
    const api = await request.newContext({ baseURL: baseURL ?? "", storageState: SESSAO });
    const eu = await api.get("/api/eu");
    await api.dispose();
    if (eu.ok()) return;
  }
  await page.goto("/entrar?volta=/historico");
  await page.getByRole("button", { name: "Entrar na demonstração" }).click();
  await page.waitForURL((url) => url.pathname === "/historico");
  await expect(page.getByRole("heading", { level: 1, name: "Histórico" })).toBeVisible();
  await page.context().storageState({ path: SESSAO });
});
