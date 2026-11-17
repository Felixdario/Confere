/**
 * Cliente da API (mesma origem, `/api/*`). Tipos gerados de `docs/openapi.json` por
 * `pnpm gerar-tipos`; nada aqui é escrito à mão além dos atalhos.
 */
import type { components } from "./api-tipos";

export type Esquemas = components["schemas"];
export type AnaliseDetalhe = Esquemas["AnaliseDetalhe"];
export type AnaliseResumo = Esquemas["AnaliseResumo"];
export type LinhaRequisito = Esquemas["LinhaRequisito"];
export type Aviso = Esquemas["Aviso"];
export type Comparacao = Esquemas["Comparacao"];
export type CurriculoDetalhe = Esquemas["CurriculoDetalhe"];
export type ProcessoResumo = Esquemas["ProcessoResumo"];
export type ProcessoDetalhe = Esquemas["ProcessoDetalhe"];
export type CandidatoRanking = Esquemas["CandidatoRanking"];
export type CandidatoDetalhe = Esquemas["CandidatoDetalhe"];
export type Privacidade = Esquemas["Privacidade"];
export type Eu = Esquemas["Eu"];
export type EstadoRequisito = LinhaRequisito["status"];

export const BASE = "/api";

/** Erro da API no formato RFC 9457 (`Problema`), com a mensagem pronta para a tela. */
export class ErroApi extends Error {
  constructor(
    readonly status: number,
    readonly codigo: string,
    mensagem: string,
    readonly campos?: Esquemas["CampoInvalido"][] | null,
  ) {
    super(mensagem);
    this.name = "ErroApi";
  }
}

let tokenCsrf: string | null = null;

async function obterCsrf(renovar = false): Promise<string> {
  if (tokenCsrf && !renovar) return tokenCsrf;
  const r = await fetch(`${BASE}/auth/csrf`, { credentials: "same-origin" });
  if (!r.ok) throw await erroDe(r);
  tokenCsrf = ((await r.json()) as Esquemas["TokenCsrf"]).csrf;
  return tokenCsrf;
}

async function erroDe(r: Response): Promise<ErroApi> {
  try {
    const p = (await r.json()) as Partial<Esquemas["Problema"]>;
    return new ErroApi(r.status, p.codigo ?? "erro", p.detail ?? p.title ?? `Erro ${r.status}`, p.campos);
  } catch {
    if (r.status >= 500 || r.status === 0) {
      return new ErroApi(r.status, "indisponivel", "O serviço não respondeu. Tente de novo em instantes.");
    }
    return new ErroApi(r.status, "erro", `Erro ${r.status}`);
  }
}

type Corpo = FormData | Record<string, unknown> | undefined;

export async function api<T>(caminho: string, opcoes: { metodo?: string; corpo?: Corpo } = {}): Promise<T> {
  const metodo = opcoes.metodo ?? "GET";
  const mudaEstado = metodo !== "GET" && metodo !== "HEAD";

  const enviar = async (renovar: boolean) => {
    const cabecalhos: Record<string, string> = { Accept: "application/json" };
    let body: BodyInit | null = null;
    if (opcoes.corpo instanceof FormData) body = opcoes.corpo;
    else if (opcoes.corpo !== undefined) {
      body = JSON.stringify(opcoes.corpo);
      cabecalhos["Content-Type"] = "application/json";
    }
    if (mudaEstado) cabecalhos["X-CSRF-Token"] = await obterCsrf(renovar);
    return fetch(`${BASE}${caminho}`, { method: metodo, body, headers: cabecalhos, credentials: "same-origin" });
  };

  let r: Response;
  try {
    r = await enviar(false);
    // O token muda com o login e o logout: uma recusa de CSRF tenta uma vez com um token novo.
    if (r.status === 403 && mudaEstado) {
      const copia = r.clone();
      const p = (await copia.json().catch(() => null)) as { codigo?: string } | null;
      if (p?.codigo === "csrf") r = await enviar(true);
    }
  } catch {
    throw new ErroApi(0, "sem_rede", "Sem conexão com o servidor. Confira a internet e tente de novo.");
  }

  if (!r.ok) throw await erroDe(r);
  if (r.status === 204) return undefined as T;
  const tipo = r.headers.get("content-type") ?? "";
  return (tipo.includes("json") ? await r.json() : await r.text()) as T;
}

/** Depois do login ou do logout, o token antigo deixa de valer. */
export function esquecerCsrf() {
  tokenCsrf = null;
}

export const VERSAO_CONSENTIMENTO_PADRAO = "2026-11-16";
