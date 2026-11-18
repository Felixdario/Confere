import AxeBuilder from "@axe-core/playwright";
import { expect, request, test, type Page } from "@playwright/test";

const SESSAO = "e2e/.sessao/demo.json";

// Todas as telas passam no axe (WCAG 2.2 AA), no tema claro e no escuro. As do app usam a sessão
// salva pelo projeto `entrar`; os ids das telas dinâmicas vêm da própria API (dados do seed).

const REGRAS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function semViolacoes(page: Page) {
  const resultado = await new AxeBuilder({ page }).withTags(REGRAS).analyze();
  const resumo = resultado.violations.map(
    (v) =>
      `${v.id} (${v.impact}): ${v.help}\n  ${v.nodes
        .map((n) => `${n.target.join(" ")}  ${n.any.map((c) => c.message).join(" ")}`)
        .join("\n  ")}`,
  );
  // Suave: junta as violações de todas as telas num relatório só.
  expect.soft(resumo, `${page.url()}\n${resumo.join("\n")}`).toEqual([]);
}

type Ids = { analise: string; comparacao: string; processo: string };

type ItemAnalise = { id: string; status: string; curriculo: { id: string }; vaga: { id: string } };

async function idsDoSeed(baseURL: string): Promise<Ids> {
  const api = await request.newContext({ baseURL, storageState: SESSAO });
  const analises = (await (await api.get("/api/analises")).json()) as { itens: ItemAnalise[] };
  const curriculos = (await (await api.get("/api/curriculos")).json()) as { id: string; versoes: unknown[] }[];
  const processos = (await (await api.get("/api/processos")).json()) as { id: string }[];
  await api.dispose();
  const analise = analises.itens.find((a) => a.status === "concluida");
  const curriculo = curriculos.find((c) => c.versoes.length > 1);
  const vaga = analises.itens.find((a) => a.curriculo.id === curriculo?.id)?.vaga.id;
  if (!analise || !curriculo || !vaga || !processos[0]) throw new Error("Rode `make seed` antes.");
  return { analise: analise.id, comparacao: `${curriculo.id}?vaga=${vaga}`, processo: processos[0].id };
}

for (const tema of ["light", "dark"] as const) {
  test.describe(`axe, tema ${tema === "light" ? "claro" : "escuro"}`, () => {
    // Sem animação de entrada: o axe lê o estado final (o que ainda vai aparecer tem opacidade 0).
    test.use({ colorScheme: tema, reducedMotion: "reduce" });

    test("telas públicas", async ({ browser }) => {
      const contexto = await browser.newContext({
        colorScheme: tema,
        reducedMotion: "reduce",
        storageState: { cookies: [], origins: [] },
      });
      const page = await contexto.newPage();
      for (const caminho of ["/", "/entrar"]) {
        await page.goto(caminho);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await semViolacoes(page);
      }
      // A landing com um requisito ausente aberto no exemplo.
      await page.goto("/");
      await page.locator("#exemplo").getByRole("button", { name: /GraphQL/ }).click();
      await semViolacoes(page);
      await contexto.close();
    });

    test("telas do app", async ({ page, baseURL }) => {
      const ids = await idsDoSeed(baseURL ?? "");
      const telas = [
        "/nova",
        "/historico",
        `/analises/${ids.analise}`,
        `/curriculos/${ids.comparacao}`,
        "/recrutador",
        `/recrutador/${ids.processo}`,
        "/privacidade",
      ];
      for (const caminho of telas) {
        await page.goto(caminho);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await page.waitForLoadState("networkidle");
        await semViolacoes(page);
      }
      // O progresso ao vivo: o seed só tem análises concluídas, então a API responde "processando"
      // e o SSE manda uma etapa e um pedaço do feedback (e fecha, o que mostra o aviso de conexão).
      await page.route(`**/api/analises/${ids.analise}`, async (rota) => {
        const resposta = await rota.fetch();
        const corpo = (await resposta.json()) as Record<string, unknown>;
        await rota.fulfill({ response: resposta, json: { ...corpo, status: "processando", nota: null, etapas: [] } });
      });
      await page.route(`**/api/analises/${ids.analise}/eventos`, (rota) =>
        rota.fulfill({
          headers: { "content-type": "text/event-stream" },
          body:
            "retry: 600000\n\n" +
            `event: etapa\ndata: ${JSON.stringify({ etapa: "extracao", texto: "lendo as competências" })}\n\n` +
            `event: texto\ndata: ${JSON.stringify({ texto: "Faltou citar GraphQL." })}\n\n`,
        }),
      );
      await page.goto(`/analises/${ids.analise}`);
      await expect(page.locator(".eixo__etapa[aria-current='step']")).toContainText("Extração");
      await expect(page.getByRole("status").filter({ hasText: "Extração: lendo as competências." })).toBeAttached();
      await semViolacoes(page);
      await page.unrouteAll();

      // A nova análise no modo "colar texto".
      await page.goto("/nova");
      await page.getByRole("button", { name: "Colar texto" }).click();
      await semViolacoes(page);
    });
  });
}
