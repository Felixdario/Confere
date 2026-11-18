"use client";

import clsx from "clsx";
import { useEffect, useRef, useState } from "react";

import { CarimboTexto } from "@/componentes/carimbo";
import { BASE, type AnaliseDetalhe } from "@/lib/api";
import { ETAPAS, type EtapaId } from "@/lib/textos";

type Fim = { status: "concluida" } | { status: "erro"; mensagem: string };

const ORDEM = ETAPAS.map((e) => e.id) as string[];

/**
 * As etapas num eixo vertical, carimbadas ao terminar, pelo SSE da análise. O evento `etapa X`
 * anuncia o começo de X; a anterior está feita. Os pedaços `texto` do feedback aparecem como
 * parágrafo corrido, sem mostrar o fluxo cru.
 */
export function Progresso({ analise, aoTerminar }: { analise: AnaliseDetalhe; aoTerminar: (fim: Fim) => void }) {
  const jaFeitas = analise.etapas.map((e) => e.etapa);
  const [atual, setAtual] = useState<string | null>(jaFeitas.at(-1) ?? null);
  const [terminou, setTerminou] = useState(false);
  const [texto, setTexto] = useState("");
  const [anuncio, setAnuncio] = useState("Na fila. A análise começa em instantes.");
  const [segundos, setSegundos] = useState(() =>
    Math.max(0, Math.round((Date.now() - new Date(analise.iniciado_em ?? analise.criado_em).getTime()) / 1000)),
  );
  const [semConexao, setSemConexao] = useState(false);
  const fimRef = useRef(aoTerminar);

  useEffect(() => {
    fimRef.current = aoTerminar;
  }, [aoTerminar]);

  useEffect(() => {
    const relogio = window.setInterval(() => setSegundos((s) => s + 1), 1000);
    const fonte = new EventSource(`${BASE}/analises/${analise.id}/eventos`);

    fonte.addEventListener("etapa", (e) => {
      const d = JSON.parse((e as MessageEvent<string>).data) as { etapa: EtapaId; texto: string };
      setSemConexao(false);
      setAtual(d.etapa);
      const nome = ETAPAS.find((x) => x.id === d.etapa)?.nome ?? d.etapa;
      setAnuncio(`${nome}: ${d.texto}.`);
    });
    fonte.addEventListener("texto", (e) => {
      const d = JSON.parse((e as MessageEvent<string>).data) as { texto: string };
      setTexto((t) => t + d.texto);
    });
    fonte.addEventListener("final", () => {
      fonte.close();
      window.clearInterval(relogio);
      setTerminou(true);
      setAnuncio("Análise concluída. Mostrando o resultado.");
      window.setTimeout(() => fimRef.current({ status: "concluida" }), 650);
    });
    fonte.addEventListener("erro", (e) => {
      fonte.close();
      window.clearInterval(relogio);
      const d = JSON.parse((e as MessageEvent<string>).data) as { mensagem: string };
      fimRef.current({ status: "erro", mensagem: d.mensagem });
    });
    fonte.onerror = () => {
      // O EventSource reconecta sozinho com Last-Event-ID; só avisamos enquanto estiver fora.
      if (fonte.readyState !== EventSource.CLOSED) setSemConexao(true);
    };
    return () => {
      fonte.close();
      window.clearInterval(relogio);
    };
  }, [analise.id]);

  const indiceAtual = atual ? ORDEM.indexOf(atual) : -1;
  const mm = String(Math.floor(segundos / 60)).padStart(2, "0");
  const ss = String(segundos % 60).padStart(2, "0");

  return (
    <div className="progresso">
      <div className="progresso__cabeca">
        <p className="progresso__agora">
          {terminou
            ? "Concluída"
            : indiceAtual < 0
              ? "Na fila"
              : (ETAPAS[indiceAtual]?.nome ?? "Em andamento")}
        </p>
        <p className="progresso__tempo numeros" role="timer" aria-label={`Tempo decorrido: ${segundos} segundos`}>
          {mm}:{ss}
        </p>
      </div>
      <p className="so-leitor" role="status" aria-live="polite">
        {anuncio}
      </p>
      {semConexao && (
        <p className="aviso" role="status">
          <strong>Conexão interrompida.</strong> Tentando de novo; a análise continua no servidor.
        </p>
      )}

      <ol className="eixo">
        {ETAPAS.map((e, i) => {
          const feita = terminou || i < indiceAtual;
          const agora = !terminou && i === indiceAtual;
          return (
            <li
              key={e.id}
              className={clsx("eixo__etapa", feita && "eixo__etapa--feita", agora && "eixo__etapa--agora")}
              aria-current={agora ? "step" : undefined}
            >
              <span className="eixo__ponto" aria-hidden="true" />
              <div className="eixo__texto">
                <p className="eixo__nome">{e.nome}</p>
                <p className="eixo__descricao">{e.texto}</p>
              </div>
              <div className="eixo__marca">
                {feita ? (
                  <CarimboTexto estado="atende" cai inclinar={-2}>
                    Feito
                  </CarimboTexto>
                ) : agora ? (
                  <span className="eixo__agora">em andamento</span>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>

      {texto && (
        <section className="bloco" aria-labelledby="feedback-parcial">
          <h2 id="feedback-parcial" className="bloco__titulo">
            Feedback
          </h2>
          <p className="progresso__feedback">{texto}</p>
        </section>
      )}
    </div>
  );
}
