import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

const caso = (arquivo: string) =>
  readFileSync(fileURLToPath(new URL(`../../../evals/casos/b01-frontend-senior/${arquivo}`, import.meta.url)), "utf8");

test.describe.configure({ mode: "serial" });

test("landing: confira você mesmo carimba o trecho ou a falta", async ({ browser }) => {
  // A landing é pública: sem a sessão salva.
  const contexto = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const page = await contexto.newPage();
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Seu currículo");
  await expect(page.getByText("Modo demonstração:").first()).toBeVisible();

  const exemplo = page.locator("#exemplo");
  await exemplo.getByRole("button", { name: /GraphQL/ }).click();
  await expect(exemplo.getByRole("heading", { name: "Isto não consta." })).toBeVisible();
  await expect(exemplo.getByRole("img", { name: "Não atende: 0" })).toBeVisible();

  await exemplo.getByRole("button", { name: /Next\.js/ }).click();
  await expect(exemplo.getByRole("heading", { name: "Só conta o que está escrito." })).toBeVisible();
  await expect(exemplo.getByRole("img", { name: "Atende: 1,0" })).toBeVisible();
  await contexto.close();
});

test("fluxo principal: entrar, analisar com progresso ao vivo e ler o resultado", async ({ page }) => {
  await page.goto("/entrar?volta=/nova");
  await page.getByRole("button", { name: "Entrar na demonstração" }).click();
  await expect(page).toHaveURL(/\/nova$/);
  await expect(page.getByRole("heading", { level: 1, name: "Nova análise" })).toBeVisible();

  await page.getByRole("button", { name: "Colar texto" }).click();
  await page.getByLabel("Texto do currículo").fill(caso("curriculo.md"));
  await page.getByLabel("Vaga", { exact: true }).fill(caso("vaga.md"));
  await page.getByRole("button", { name: "Analisar" }).click();

  await expect(page).toHaveURL(/\/analises\/[0-9a-f-]+$/);
  // O resultado chega pelo SSE: a nota do caso b01 no modo regras é 90.
  await expect(page.getByLabel("Nota 90 de 100")).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText("Atende todos os 5 obrigatórios")).toBeVisible();

  const tabela = page.getByRole("table", { name: /Requisitos da vaga/ });
  await expect(tabela.getByRole("row", { name: /GraphQL/ }).getByRole("img", { name: "Não atende: 0" })).toBeVisible();
  await expect(tabela.getByRole("row", { name: /Inglês avançado/ }).getByRole("img", { name: "Parcial: 0,5" })).toBeVisible();
  await expect(page.getByText("obrigatórios 5 de 5")).toBeVisible();
  await expect(page.getByRole("heading", { name: "O que foi removido antes da leitura" })).toBeVisible();

  await page.goto("/historico");
  await expect(page.getByRole("heading", { level: 1, name: "Histórico" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Comparar versões" }).first()).toBeVisible();
  await page.getByRole("link", { name: "Comparar versões" }).first().click();
  await expect(page.getByRole("heading", { name: "O que mudou, requisito por requisito" })).toBeVisible();
});

test("recrutador: triagem anonimizada com decisão humana", async ({ page }) => {
  await page.goto("/recrutador");
  await expect(page.getByRole("heading", { level: 1, name: "Recrutador" })).toBeVisible();
  await page.getByRole("link", { name: /demonstração/ }).first().click();
  await expect(page.getByText(/atendem todos os obrigatórios/)).toBeVisible();
  await expect(page.getByRole("button", { name: /^Candidato [A-Z]+$/ }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Decisão" })).toBeVisible();
});
