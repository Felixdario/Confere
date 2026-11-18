"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";

import { Carregando, Erro } from "@/componentes/moldura";
import { api, type AnaliseResumo, type Esquemas } from "@/lib/api";
import { useExigirSessao } from "@/lib/sessao";
import { data, dataCurta, ORIGEM } from "@/lib/textos";

import "./historico.css";

interface Grupo {
  chave: string;
  curriculoId: string;
  vaga: AnaliseResumo["vaga"];
  versoes: AnaliseResumo[]; // da mais recente para a mais antiga
}

function agrupar(itens: AnaliseResumo[]): Grupo[] {
  const grupos = new Map<string, Grupo>();
  for (const a of itens) {
    const chave = `${a.curriculo.id}|${a.vaga.id}`;
    const g = grupos.get(chave) ?? { chave, curriculoId: a.curriculo.id, vaga: a.vaga, versoes: [] };
    g.versoes.push(a);
    grupos.set(chave, g);
  }
  return [...grupos.values()];
}

const concluidas = (g: Grupo) => g.versoes.filter((v) => v.status === "concluida" && v.nota !== null);

function diferenca(g: Grupo): { nota: number; delta: number; anterior: AnaliseResumo } | null {
  const [atual, anterior] = concluidas(g);
  if (!atual || !anterior || atual.nota === null || anterior.nota === null) return null;
  return { nota: atual.nota, delta: atual.nota - anterior.nota, anterior };
}

const sinal = (n: number) => (n > 0 ? `+${n}` : n < 0 ? `−${Math.abs(n)}` : "0");

const ESTADO = { na_fila: "na fila", processando: "analisando", concluida: "concluída", erro: "erro" } as const;

export default function Historico() {
  const eu = useExigirSessao();
  const q = useInfiniteQuery({
    queryKey: ["analises"],
    queryFn: ({ pageParam }) =>
      api<Esquemas["PaginaAnalises"]>(`/analises?limite=50${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`),
    initialPageParam: "",
    getNextPageParam: (p) => p.proximo_cursor ?? undefined,
    enabled: !!eu.data,
  });

  if (!eu.data || q.isPending) return <Carregando texto="Abrindo o histórico…" />;
  if (q.isError) return <Erro erro={q.error} tentar={() => void q.refetch()} />;

  const itens = q.data.pages.flatMap((p) => p.itens);
  const grupos = agrupar(itens);
  const comMudanca = grupos.map(diferenca).find((d) => d !== null);
  const achado = comMudanca
    ? `${comMudanca.nota}, ${sinal(comMudanca.delta)} em relação à versão de ${dataCurta(comMudanca.anterior.criado_em)}.`
    : `${itens.length} ${itens.length === 1 ? "análise" : "análises"} em ${grupos.length} ${grupos.length === 1 ? "vaga" : "vagas"}.`;

  return (
    <>
      <title>Histórico · Confere</title>
      <div className="cabeca-tela">
        <div>
          <h1 className="titulo-tela">Histórico</h1>
          {itens.length > 0 && <p className="subtitulo-tela numeros">{achado}</p>}
        </div>
        <div className="cabeca-tela__acoes">
          <Link className="botao" href="/nova">
            Nova análise
          </Link>
        </div>
      </div>

      {itens.length === 0 ? (
        <div className="vazio">
          <p>Nenhuma análise ainda. Envie um currículo e uma vaga; o resultado fica aqui para comparar com as próximas versões.</p>
          <Link className="botao" href="/nova">
            Fazer a primeira análise
          </Link>
        </div>
      ) : (
        <ul className="pilhas">
          {grupos.map((g) => {
            const [topo, ...anteriores] = g.versoes;
            if (!topo) return null;
            const d = diferenca(g);
            const podeComparar = concluidas(g).length >= 2;
            return (
              <li key={g.chave} className="pilha">
                <div className="pilha__folhas" data-camadas={Math.min(anteriores.length, 2)}>
                  <article className="pilha__folha">
                    <div className="pilha__cabeca">
                      <h2 className="pilha__vaga">
                        <Link href={`/analises/${topo.id}`}>{g.vaga.titulo}</Link>
                      </h2>
                      <p className="pilha__nota numeros" role="img" aria-label={topo.nota !== null ? `Nota ${topo.nota}` : ESTADO[topo.status]}>
                        {topo.nota ?? "—"}
                      </p>
                    </div>
                    <p className="pilha__meta numeros">
                      Versão {topo.curriculo.versao} · {ORIGEM[topo.curriculo.origem]} · {data(topo.criado_em)}
                      {topo.status !== "concluida" && ` · ${ESTADO[topo.status]}`}
                      {d && (
                        <span className={clsx("pilha__delta", d.delta > 0 && "pilha__delta--sobe")}>
                          {" "}
                          · {sinal(d.delta)} desde a versão {d.anterior.curriculo.versao}
                        </span>
                      )}
                    </p>
                    <div className="pilha__acoes">
                      <Link href={`/analises/${topo.id}`}>Ver resultado</Link>
                      {podeComparar && <Link href={`/curriculos/${g.curriculoId}?vaga=${g.vaga.id}`}>Comparar versões</Link>}
                      <Link
                        href={`/nova?curriculo=${g.curriculoId}&vaga=${g.vaga.id}&titulo=${encodeURIComponent(g.vaga.titulo)}`}
                      >
                        Enviar nova versão
                      </Link>
                    </div>
                  </article>
                </div>
                {anteriores.length > 0 && (
                  <ol className="pilha__anteriores" aria-label="Versões anteriores">
                    {anteriores.map((v) => (
                      <li key={v.id}>
                        <Link href={`/analises/${v.id}`} className="numeros">
                          <span>Versão {v.curriculo.versao}</span>
                          <span>{data(v.criado_em)}</span>
                          <span className="pilha__nota-antiga">{v.nota ?? ESTADO[v.status]}</span>
                        </Link>
                      </li>
                    ))}
                  </ol>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {q.hasNextPage && (
        <p className="bloco">
          <button type="button" className="botao botao--secundario" onClick={() => void q.fetchNextPage()} disabled={q.isFetchingNextPage}>
            {q.isFetchingNextPage ? "Carregando…" : "Carregar análises mais antigas"}
          </button>
        </p>
      )}
    </>
  );
}
