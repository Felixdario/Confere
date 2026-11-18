import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

// Capturas do README (docs/capturas). Fora da suíte normal: só roda com CAPTURAS=1, no projeto desktop.
//   CAPTURAS=1 corepack pnpm test:e2e --project=desktop capturas
test.skip(!process.env.CAPTURAS, "só com CAPTURAS=1");
test.describe.configure({ mode: "serial" });

const destino = (nome: string) =>
  fileURLToPath(new URL(`../../../docs/capturas/${nome}.png`, import.meta.url));

async function capturar(page: Page, nome: string, inteira = false) {
  await page.evaluate(() => document.fonts.ready);
  // Esconde o que só existe em dev: o indicador do Next e o seletor de dados do break-ui (D-64).
  await page.addStyleTag({
    content:
      "nextjs-portal,[aria-label='Dados de teste (desenvolvimento)']{display:none!important}" +
      "*,*::before,*::after{animation:none!important;transition:none!important}",
  });
  await page.waitForTimeout(300);
  await page.screenshot({ path: destino(nome), fullPage: inteira });
}

test.beforeEach(({}, info) => {
  test.skip(info.project.name !== "desktop", "capturas só no desktop");
});

test.use({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, contextOptions: { reducedMotion: "reduce" } });

test("landing", async ({ browser }) => {
  const contexto = await browser.newContext({
    storageState: { cookies: [], origins: [] },
    viewport: { width: 1440, height: 900 },
    locale: "pt-BR",
    reducedMotion: "reduce",
  });
  const page = await contexto.newPage();
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await capturar(page, "landing");
  const exemplo = page.locator("#exemplo");
  await exemplo.getByRole("button", { name: /GraphQL/ }).click();
  await expect(exemplo.getByRole("heading", { name: "Isto não consta." })).toBeVisible();
  await exemplo.scrollIntoViewIfNeeded();
  await exemplo.screenshot({ path: destino("landing-exemplo") });
  await contexto.close();
});

test("resultado e comparação", async ({ page }) => {
  await page.goto("/historico");
  await expect(page.getByRole("heading", { level: 1, name: "Histórico" })).toBeVisible();

  await page.getByRole("link", { name: "Comparar versões" }).first().click();
  await expect(page.getByRole("heading", { name: "O que mudou, requisito por requisito" })).toBeVisible();
  await capturar(page, "comparacao", true);

  // O seed mistura o provedor falso (gravações) e as regras; a captura mostra uma análise por
  // regras (a versão 1 do b01), o padrão de quem roda o repositório.
  await page.goto("/historico");
  await expect(page.getByRole("link", { name: "Comparar versões" }).first()).toBeVisible();
  const links = await page.locator('a[href^="/analises/"]').evaluateAll((as) =>
    [...new Set(as.map((a) => a.getAttribute("href") ?? ""))],
  );
  let achou = false;
  for (const href of links) {
    await page.goto(href);
    await expect(page.getByLabel(/^Nota \d+ de 100$/)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("heading", { name: "Feedback" })).toBeVisible();
    const porRegras = (await page.locator("main").innerText()).includes("Esta análise foi feita por regras");
    if (porRegras) {
      achou = true;
      break;
    }
  }
  expect(achou, "nenhuma análise por regras no histórico").toBe(true);
  await capturar(page, "resultado", true);
});

test("recrutador", async ({ page }) => {
  await page.goto("/recrutador");
  await expect(page.getByRole("heading", { level: 1, name: "Recrutador" })).toBeVisible();
  await page.getByRole("link", { name: /demonstração/ }).first().click();
  await expect(page.getByRole("heading", { name: "Decisão" })).toBeVisible();
  await capturar(page, "recrutador", true);
});
