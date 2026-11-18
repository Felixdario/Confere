"use client";

import NumberFlow from "@number-flow/react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Carimbo } from "@/componentes/carimbo";
import { BASE, type AnaliseDetalhe, type LinhaRequisito } from "@/lib/api";
import {
  dataHora,
  fraseDoAviso,
  NOME_DO_DADO,
  ORIGEM,
  ROTULO_DO_TIPO,
  valorDoRequisito,
} from "@/lib/textos";

/** "Faltam 2 de 6 obrigatórios: Docker e Kubernetes (em parte)." */
export function achadoDosObrigatorios(requisitos: LinhaRequisito[]): string {
  const obrig = requisitos.filter((r) => r.tipo === "obrigatorio");
  if (obrig.length === 0) return "A vaga não lista requisitos obrigatórios; a nota vem dos desejáveis e da senioridade.";
  const faltam = obrig.filter((r) => r.status !== "atende");
  if (faltam.length === 0) {
    return obrig.length === 1
      ? "Atende o único obrigatório, com o trecho que comprova."
      : `Atende todos os ${obrig.length} obrigatórios, cada um com o trecho que comprova.`;
  }
  const nomes = faltam.map((r) => (r.status === "parcial" ? `${r.competencia_pedida} (em parte)` : r.competencia_pedida));
  const lista = nomes.length > 1 ? `${nomes.slice(0, -1).join(", ")} e ${nomes.at(-1)}` : nomes[0];
  const verbo = faltam.length === 1 ? "Falta" : "Faltam";
  return `${verbo} ${faltam.length} de ${obrig.length} ${obrig.length === 1 ? "obrigatório" : "obrigatórios"}: ${lista}.`;
}

const NOME_DA_PARCELA: Record<string, string> = {
  obrigatorios: "obrigatórios",
  desejaveis: "desejáveis",
  senioridade: "senioridade",
};

/**
 * "Obrigatórios pesam 70 %, desejáveis 20 % e senioridade 10 %". A nota divide pelos pesos
 * presentes (nota.py), então uma vaga sem obrigatórios mostra os pesos redistribuídos.
 */
export function frasePesos(parcelas: { componente: string; peso: string }[]): string {
  const fracao = (p: string) => {
    const [n, d] = p.split("/").map(Number);
    return (n ?? 0) / (d ?? 1);
  };
  const soma = parcelas.reduce((t, p) => t + fracao(p.peso), 0);
  const unica = parcelas[0];
  if (soma === 0 || !unica) return "";
  if (parcelas.length === 1) {
    const nome = NOME_DA_PARCELA[unica.componente] ?? unica.componente;
    return `A nota vem só ${unica.componente === "senioridade" ? "da" : "dos"} ${nome}`;
  }
  const fmt = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
  const partes = parcelas.map(
    (p) => `${NOME_DA_PARCELA[p.componente] ?? p.componente} ${fmt.format((100 * fracao(p.peso)) / soma)} %`,
  );
  const lista = `${partes.slice(0, -1).join(", ")} e ${partes.at(-1)}`;
  return `${lista.charAt(0).toUpperCase()}${lista.slice(1)}`.replace(/^(\S+)/, "$1 pesam");
}

function Nota({ nota }: { nota: number }) {
  // A nota se acerta uma vez, da esquerda para a direita, a partir de zero.
  const [valor, setValor] = useState(0);
  useEffect(() => {
    const t = window.setTimeout(() => setValor(nota), 120);
    return () => window.clearTimeout(t);
  }, [nota]);
  return (
    // `role="img"`: o rótulo vale para o bloco inteiro (num `<p>`, o aria-label é proibido).
    <p className="nota" role="img" aria-label={`Nota ${nota} de 100`}>
      <NumberFlow value={valor} className="nota__numero" aria-hidden="true" willChange />
      <span className="nota__de" aria-hidden="true">
        de 100
      </span>
    </p>
  );
}

function Requisitos({ requisitos }: { requisitos: LinhaRequisito[] }) {
  const ordem = { nao_atende: 0, parcial: 1, atende: 2 } as const;
  const linhas = [...requisitos].sort(
    (a, b) => (a.tipo === b.tipo ? ordem[a.status] - ordem[b.status] : a.tipo === "obrigatorio" ? -1 : 1),
  );
  return (
    <div className="rolagem-x" role="region" aria-label="Requisitos da vaga" tabIndex={0}>
      <table className="tabela requisitos">
        <caption className="so-leitor">Requisitos da vaga, o estado de cada um e o trecho que comprova</caption>
        <thead>
          <tr>
            <th scope="col">Requisito</th>
            <th scope="col">Estado</th>
            <th scope="col" className="direita">
              Vale
            </th>
            <th scope="col">Trecho do currículo</th>
          </tr>
        </thead>
        <tbody>
          {linhas.map((r) => (
            <tr key={`${r.tipo}-${r.descricao}`} data-estado={r.status}>
              <td className="requisitos__nome">
                <span>{r.descricao}</span>
                <span className="requisitos__tipo">{ROTULO_DO_TIPO[r.tipo]}</span>
              </td>
              <td>
                <Carimbo estado={r.status} valor={r.valor} />
              </td>
              <td className="numeros">{valorDoRequisito(r.valor)}</td>
              <td className="requisitos__trecho">
                {r.evidencia ? <q className="trecho">{r.evidencia}</q> : <span className="requisitos__falta">Nenhum trecho.</span>}
                <span className="requisitos__motivo">{r.motivo.charAt(0).toUpperCase() + r.motivo.slice(1)}.</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Resultado({ a }: { a: AnaliseDetalhe }) {
  const nota = a.nota ?? 0;
  const d = a.decomposicao;
  return (
    <>
      <div className="cabeca-tela">
        <div>
          <h1 className="titulo-tela">{a.vaga.titulo}</h1>
          <p className="subtitulo-tela">{achadoDosObrigatorios(a.requisitos)}</p>
        </div>
        <div className="cabeca-tela__acoes">
          <a className="botao botao--secundario" href={`${BASE}/analises/${a.id}/relatorio.pdf`} download>
            Exportar PDF
          </a>
          <Link
            className="botao"
            href={`/nova?curriculo=${a.curriculo.id}&vaga=${a.vaga.id}&titulo=${encodeURIComponent(a.vaga.titulo)}`}
          >
            Enviar nova versão
          </Link>
        </div>
      </div>

      {a.conteudo_apagado && (
        <div className="aviso" role="note">
          <strong>O texto desta versão já foi apagado pela retenção.</strong>
          <p>A nota e os estados continuam; os trechos citados não estão mais guardados.</p>
        </div>
      )}

      <section className="placar" aria-label="Nota e conta">
        <Nota nota={nota} />
        <div className="placar__conta">
          <p className="placar__rotulo">A conta</p>
          {d && (
            <ul className="conta-linhas numeros">
              {d.parcelas.map((p) => (
                <li key={p.componente}>
                  <span>{p.resumo.split(" → ")[0]}</span>
                  <span className="conta-linhas__pontos">{p.pontos_exibicao}</span>
                </li>
              ))}
              <li className="conta-linhas__total">
                <span>nota</span>
                <span className="conta-linhas__pontos">{nota}</span>
              </li>
            </ul>
          )}
          <p className="nota-rodape">
            {d ? frasePesos(d.parcelas) : "Obrigatórios pesam 70 %, desejáveis 20 % e senioridade 10 %"}
            {d?.anos_minimos ? `; a vaga pede ${d.anos_minimos} anos` : ""}. Versão {a.curriculo.versao} ({ORIGEM[a.curriculo.origem]}),
            concluída em {a.concluido_em ? dataHora(a.concluido_em) : "—"}.
          </p>
        </div>
      </section>

      {a.avisos.length > 0 && (
        <section className="bloco" aria-labelledby="avisos-titulo">
          <h2 id="avisos-titulo" className="bloco__titulo">
            Avisos
          </h2>
          {a.avisos.map((v, i) => {
            const f = fraseDoAviso(v.tipo, v.motivo);
            return (
              <div key={i} className="aviso">
                <strong>{f.titulo}</strong>
                <p>
                  {f.feito}
                  {v.trecho ? (
                    <>
                      {" "}
                      Trecho: <q className="trecho">{v.trecho}</q>
                      {v.pagina ? ` (página ${v.pagina})` : ""}
                    </>
                  ) : null}
                </p>
              </div>
            );
          })}
        </section>
      )}

      <section className="bloco" aria-labelledby="requisitos-titulo">
        <h2 id="requisitos-titulo" className="bloco__titulo">
          Requisito por requisito
        </h2>
        <Requisitos requisitos={a.requisitos} />
      </section>

      <div className="duas-colunas">
        <section className="bloco" aria-labelledby="lacunas-titulo">
          <h2 id="lacunas-titulo" className="bloco__titulo">
            O que falta comprovar
          </h2>
          {a.lacunas.length === 0 ? (
            <p>Nenhuma lacuna: todos os requisitos têm trecho.</p>
          ) : (
            <ul className="lista-marcada">
              {a.lacunas.map((l) => (
                <li key={l.requisito}>
                  <strong>{l.requisito}.</strong> {l.comentario}
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="bloco" aria-labelledby="aprender-titulo">
          <h2 id="aprender-titulo" className="bloco__titulo">
            O que aprender
          </h2>
          {a.o_que_aprender.length === 0 ? (
            <p>Nada a aprender para esta vaga.</p>
          ) : (
            <ul className="lista-marcada">
              {a.o_que_aprender.map((l) => (
                <li key={l.competencia}>
                  <strong>{l.competencia}.</strong> {l.sugestao}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="bloco" aria-labelledby="reescritas-titulo">
        <h2 id="reescritas-titulo" className="bloco__titulo">
          Reescritas
        </h2>
        {a.reescritas.length === 0 ? (
          <p className="nota-rodape">
            {a.modo_demonstracao
              ? "No modo demonstração, sem IA, o sistema não sugere reescritas: ele aponta o que a vaga pede e onde o currículo já mostra isso."
              : "Nenhuma reescrita passou pelo filtro da evidência."}
            {a.reescritas_descartadas > 0 && ` ${a.reescritas_descartadas} foram descartadas por citar competência sem trecho.`}
          </p>
        ) : (
          <div className="reescritas">
            {a.reescritas.map((r) => (
              <div key={r.antes} className="reescrita">
                <div>
                  <p className="reescrita__rotulo">Antes</p>
                  <p className="documento reescrita__antes">{r.antes}</p>
                </div>
                <div>
                  <p className="reescrita__rotulo">Depois</p>
                  <p className="documento">{r.depois}</p>
                </div>
                <p className="nota-rodape reescrita__base">Usa só competências com trecho: {r.competencias.join(", ")}.</p>
              </div>
            ))}
          </div>
        )}
      </section>

      <div className="duas-colunas">
        <section className="bloco" aria-labelledby="ats-titulo">
          <h2 id="ats-titulo" className="bloco__titulo">
            Palavras-chave da vaga
          </h2>
          <p className="nota-rodape">Escritas assim, ao pé da letra, como um filtro automático procura.</p>
          <ul className="palavras">
            {a.palavras_chave.map((p) => (
              <li key={p.termo} data-tem={p.no_curriculo}>
                <span>{p.termo}</span>
                <span className="palavras__estado">{p.no_curriculo ? "no currículo" : "não aparece"}</span>
              </li>
            ))}
          </ul>
        </section>
        <section className="bloco" aria-labelledby="removido-titulo">
          <h2 id="removido-titulo" className="bloco__titulo">
            O que foi removido antes da leitura
          </h2>
          {a.ignorado.length === 0 ? (
            <p>Nenhum dado pessoal encontrado.</p>
          ) : (
            <ul className="removidos">
              {a.ignorado.map((i) => (
                <li key={i.tipo}>
                  <span>{NOME_DO_DADO[i.tipo] ?? i.tipo}</span>
                  <span className="numeros removidos__mascara">
                    {i.mascarado}
                    {i.ocorrencias > 1 ? ` · ${i.ocorrencias}×` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {a.resumo && (
        <section className="bloco" aria-labelledby="resumo-titulo">
          <h2 id="resumo-titulo" className="bloco__titulo">
            Feedback
          </h2>
          <p className="resumo">{a.resumo}</p>
        </section>
      )}
    </>
  );
}
