"use client";

import clsx from "clsx";
import { useState } from "react";

import { Carimbo } from "@/componentes/carimbo";
import { curriculoExemplo, requisitosExemplo, titulosExemplo } from "@/dados/exemplo-b01";
import { ROTULO_DO_ESTADO, ROTULO_DO_TIPO, valorDoRequisito } from "@/lib/textos";

const linhaDa = (evidencia: string | null) =>
  evidencia === null ? -1 : curriculoExemplo.findIndex((l) => l === evidencia || l.includes(evidencia));

/**
 * "Confira você mesmo": toca-se num requisito da vaga e o carimbo cai sobre o trecho do currículo
 * que o comprova, ou "NÃO CONSTA" cai na margem. Teclado: cada requisito é um botão.
 */
export function ConfiraVoceMesmo() {
  const [escolhido, setEscolhido] = useState(0);
  const [vez, setVez] = useState(0);
  const req = requisitosExemplo[escolhido] ?? requisitosExemplo[0]!;
  const linha = linhaDa(req.evidencia);
  const falta = req.status === "nao_atende";

  return (
    <div className="confira">
      <div className="confira__lado">
        <h2 className="confira__titulo" aria-live="polite">
          {falta ? "Isto não consta." : "Só conta o que está escrito."}
        </h2>
        <p className="confira__frase">
          Toque num requisito da vaga e confira no currículo de exemplo. É um caso fictício do conjunto de
          testes, já anonimizado.
        </p>
        <ul className="confira__requisitos" aria-label="Requisitos da vaga de exemplo">
          {requisitosExemplo.map((r, i) => (
            <li key={r.descricao}>
              <button
                type="button"
                className={clsx("confira__requisito", i === escolhido && "confira__requisito--ativo")}
                aria-pressed={i === escolhido}
                onClick={() => {
                  setEscolhido(i);
                  setVez((v) => v + 1);
                }}
              >
                <span className="confira__descricao">{r.descricao}</span>
                <span className="confira__tipo">
                  {ROTULO_DO_TIPO[r.tipo]} · {ROTULO_DO_ESTADO[r.status].toLowerCase()}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      <figure className="confira__folha" data-ui aria-label="Currículo de exemplo, anonimizado">
        <div className="confira__margem">
          {falta && (
            <div className="confira__nao-consta" key={`falta-${vez}`}>
              <Carimbo estado="nao_atende" valor={req.valor} grande cai chave={req.descricao} />
              <p>Nenhum trecho do currículo fala de {req.descricao}.</p>
            </div>
          )}
        </div>
        <div className="confira__documento">
          {curriculoExemplo.map((l, i) => {
            const marcada = i === linha;
            if (titulosExemplo.has(l)) {
              return (
                <p key={l} className="confira__secao">
                  {l}
                </p>
              );
            }
            return (
              <p
                key={l}
                className={clsx(
                  "confira__linha",
                  l.startsWith("[") && "confira__linha--removida",
                  marcada && "confira__linha--marcada",
                  marcada && `confira__linha--${req.status}`,
                )}
              >
                <span>{l}</span>
                {marcada && (
                  <Carimbo
                    key={vez}
                    estado={req.status}
                    valor={req.valor}
                    grande
                    cai
                    chave={req.descricao}
                    className="confira__carimbo"
                  />
                )}
              </p>
            );
          })}
        </div>
        <figcaption className="confira__legenda">
          <span className="numeros">
            {req.descricao}: vale {valorDoRequisito(req.valor)}.
          </span>{" "}
          {req.motivo.charAt(0).toUpperCase() + req.motivo.slice(1)}.
        </figcaption>
      </figure>
    </div>
  );
}
