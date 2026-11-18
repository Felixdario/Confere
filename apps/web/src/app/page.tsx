import Link from "next/link";

import { Carimbo, CarimboTexto } from "@/componentes/carimbo";
import { FormNovaAnalise } from "@/componentes/form-nova-analise";
import {
  contaExemplo,
  curriculoExemplo,
  notaExemplo,
  removidosExemplo,
  requisitosExemplo,
  titulosExemplo,
  vagaExemplo,
} from "@/dados/exemplo-b01";
import { ETAPAS, PALAVRA_DO_CARIMBO, valorDoRequisito } from "@/lib/textos";

import { ConfiraVoceMesmo } from "./_landing/confira";
import { AcervoCrossfade, EnviarCurriculo, FichasComAbas, FrasesComChaves, Revelador, VideoCarimbo } from "./_landing/interativos";
import "./landing.css";

// Os três carimbos pousados na folha do hero: duas conferências e a falta, do caso de exemplo.
const POUSADOS = ["Next.js", "Testes automatizados com Jest", "Inglês avançado"]
  .map((d) => requisitosExemplo.find((r) => r.descricao === d)!)
  .map((r) => ({ ...r, linha: curriculoExemplo.findIndex((l) => r.evidencia !== null && l.includes(r.evidencia)) }));

const LADRILHOS: { valor: string; texto: string; detalhe: string; medido: boolean }[] = [
  { valor: "100 %", texto: "dos itens mantidos têm trecho no texto", detalhe: "369 de 369", medido: true },
  { valor: "15 de 16", texto: "notas dentro da faixa anotada à mão", detalhe: "93,8 % dos pares-base", medido: true },
  { valor: "6 de 6", texto: "currículos com ordem escondida foram sinalizados", detalhe: "diferença de nota: 0", medido: true },
  { valor: "0 de 89", texto: "frases legítimas confundidas com injection", detalhe: "falsos positivos", medido: true },
  { valor: "204 de 204", texto: "dados pessoais anotados foram removidos", detalhe: "anonimização", medido: true },
  { valor: "0 ponto", texto: "de diferença ao trocar nome, gênero ou idade", detalhe: "4 grupos contrafactuais", medido: true },
  { valor: "0,97", texto: "de precisão nas competências extraídas", detalhe: "cobertura de 1,00", medido: true },
  { valor: "Sem IA", texto: "custo, latência e extração com o modelo de IA ficaram de fora", detalhe: "o provedor de IA não foi rodado", medido: false },
];

const PAINEIS_TOM = ["#0E1426", "#132048", "#18306F", "#1F4FD8", "#4C6FE0", "#A9BAF2", "#E6ECFC"];

export default function Landing() {
  return (
    <div className="landing">
      <Revelador />
      <a href="#conteudo" className="pular">
        Pular para o conteúdo
      </a>

      {/* Hero: cartão ao lado da sala */}
      <header className="hero" id="conteudo">
        <div className="hero__cartao">
          <div className="faixa" aria-hidden="true">
            {Array.from({ length: 24 }, (_, i) => (
              <span key={i} />
            ))}
          </div>
          <div className="hero__miolo">
            <p className="marca">
              <CarimboTexto estado="neutro">Confere</CarimboTexto>
            </p>
            <h1 className="hero__titulo">
              Seu currículo,
              <br />
              conferido.
            </h1>
            <p className="hero__frase">
              Cole a vaga, envie o currículo e veja cada requisito com o trecho que o comprova, ou a falta
              dele.
            </p>
            <EnviarCurriculo />
            <nav className="hero__links" aria-label="Nesta página">
              <a href="#exemplo">Ver um exemplo</a>
              <a href="#como">Como a nota é feita</a>
              <Link href="/privacidade">Privacidade</Link>
              <Link href="/entrar">Entrar</Link>
            </nav>
          </div>
        </div>

        <div className="hero__sala">
          <svg className="hero__gigante" viewBox="0 0 1400 150" aria-hidden="true" focusable="false">
            <rect width="1400" height="150" />
            <text x="34" y="122" fontSize="128">
              CONFERE COM O ORIGINAL
            </text>
          </svg>
          <figure className="folha-exemplo" data-ui aria-label="Currículo de exemplo já conferido">
            <p className="folha-exemplo__cabecalho">
              <span>{vagaExemplo.titulo}</span>
              <span className="numeros">
                nota <strong>{notaExemplo}</strong>
              </span>
            </p>
            <div className="folha-exemplo__texto">
              {curriculoExemplo.slice(0, 13).map((l, i) => {
                const pousado = POUSADOS.find((p) => p.linha === i);
                if (titulosExemplo.has(l)) {
                  return (
                    <p key={l} className="folha-exemplo__secao">
                      {l}
                    </p>
                  );
                }
                return (
                  <p key={l} className={l.startsWith("[") ? "folha-exemplo__removida" : undefined}>
                    {l}
                    {pousado && (
                      <Carimbo
                        estado={pousado.status}
                        valor={pousado.valor}
                        grande
                        chave={pousado.descricao}
                        className="folha-exemplo__carimbo"
                      />
                    )}
                  </p>
                );
              })}
            </div>
            <figcaption className="folha-exemplo__legenda">
              Caso fictício b01, anonimizado: {removidosExemplo.join(", ")} saíram antes da leitura.
            </figcaption>
          </figure>
        </div>
      </header>

      <main>
        {/* showcase: um controle, ampliado */}
        <section className="secao secao--noite" id="exemplo" aria-labelledby="exemplo-titulo">
          <span id="exemplo-titulo" className="so-leitor">
            Confira você mesmo
          </span>
          <ConfiraVoceMesmo />
          <noscript>
            <table className="tabela-estatica">
              <caption>Requisitos da vaga de exemplo e o trecho que comprova cada um</caption>
              <thead>
                <tr>
                  <th scope="col">Requisito</th>
                  <th scope="col">Estado</th>
                  <th scope="col">Trecho do currículo</th>
                </tr>
              </thead>
              <tbody>
                {requisitosExemplo.map((r) => (
                  <tr key={r.descricao}>
                    <td>{r.descricao}</td>
                    <td>
                      {PALAVRA_DO_CARIMBO[r.status]} ({valorDoRequisito(r.valor)})
                    </td>
                    <td>{r.evidencia ?? "não consta"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </noscript>
        </section>

        <div className="faixa faixa--larga" aria-hidden="true">
          {Array.from({ length: 60 }, (_, i) => (
            <span key={i} />
          ))}
        </div>

        {/* how-it-works: sanfona de painéis tingidos */}
        <section className="secao como" id="como" aria-labelledby="como-titulo">
          <div className="como__cabeca revela">
            <h2 id="como-titulo" className="titulo-secao">
              A nota é uma conta à vista.
            </h2>
            <p className="texto-secao">
              Sete etapas, da leitura do arquivo ao feedback. São as mesmas que você acompanha na tela
              enquanto a análise roda.
            </p>
          </div>
          <div className="paineis">
            {ETAPAS.map((e, i) => (
              <details
                key={e.id}
                className="painel"
                style={{ "--tom": PAINEIS_TOM[i], "--tinta-painel": i >= 5 ? "var(--tinta)" : "#fff" } as React.CSSProperties}
                open={e.id === "nota"}
              >
                <summary className="painel__nome">
                  <span>{e.nome}</span>
                </summary>
                <div className="painel__corpo">
                  <p>{e.texto}</p>
                  {e.id === "nota" && (
                    <p className="conta numeros">
                      {contaExemplo.map((c) => (
                        <span key={c}>{c}</span>
                      ))}
                      <span className="conta__nota">nota {notaExemplo}</span>
                    </p>
                  )}
                </div>
              </details>
            ))}
          </div>
        </section>

        {/* features: frases com chaves */}
        <section className="secao recursos" aria-labelledby="recursos-titulo">
          <div className="recursos__texto revela">
            <h2 id="recursos-titulo" className="titulo-secao">
              Protege você e não inventa nada.
            </h2>
            <p className="texto-secao">Ligue cada chave para ver o que acontece por trás da frase.</p>
            <FrasesComChaves />
          </div>
          <div className="recursos__acervo">
            <AcervoCrossfade />
          </div>
        </section>

        {/* proof: marcas grandes em ladrilhos */}
        <section className="secao prova" aria-labelledby="prova-titulo">
          <div className="ladrilhos">
            <div className="ladrilho ladrilho--duplo revela">
              <h2 id="prova-titulo" className="titulo-secao">
                O que foi testado.
              </h2>
              <p>
                30 casos fictícios de currículo e vaga, com gabarito anotado à mão: 16 pares-base, 8
                contrafactuais e 6 com ordens escondidas. Números do modo regras, o mesmo que roda aqui.
              </p>
              <p>O relatório completo está em docs/evals-regras.md, no repositório.</p>
            </div>
            {LADRILHOS.map((l) => (
              <div key={l.texto} className={l.medido ? "ladrilho" : "ladrilho ladrilho--nao-medido"}>
                <p className="ladrilho__linha">
                  <span className="ladrilho__valor numeros">{l.valor}</span>
                  <CarimboTexto estado={l.medido ? "atende" : "nao_atende"}>
                    {l.medido ? "Medido · regras" : "Não medido"}
                  </CarimboTexto>
                </p>
                <p className="ladrilho__texto">
                  {l.texto} <span className="numeros">({l.detalhe})</span>
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* faq: fichas de arquivo com abas */}
        <section className="secao duvidas" aria-labelledby="duvidas-titulo">
          <div className="duvidas__lado revela">
            <h2 id="duvidas-titulo" className="titulo-secao">
              Antes de enviar.
            </h2>
            <VideoCarimbo />
          </div>
          <FichasComAbas />
        </section>

        {/* cta: o primeiro passo já aberto */}
        <section className="secao secao--carimbo cta" id="comecar" aria-labelledby="cta-titulo">
          <div className="cta__texto">
            <h2 id="cta-titulo" className="cta__titulo">
              Confira o seu.
            </h2>
            <p className="cta__frase">
              Envie o currículo e cole a vaga. Em segundos, cada requisito aparece com o trecho que o
              comprova, a conta da nota e o que falta aprender. Para o exemplo, não precisa de conta.
            </p>
          </div>
          <div className="cta__caixa">
            <FormNovaAnalise compacto />
          </div>
        </section>
      </main>

      {/* footer: a marca construída */}
      <footer className="rodape">
        <p className="rodape__marca" role="img" aria-label="Confere">
          {"CONFERE".split("").map((c, i) => (
            <span key={i} style={{ "--altura": `${[100, 86, 94, 78, 100, 88, 96][i]}%` } as React.CSSProperties}>
              {c}
            </span>
          ))}
        </p>
        <div className="rodape__linhas">
          <nav aria-label="Rodapé">
            <Link href="/nova">Nova análise</Link>
            <Link href="/historico">Histórico</Link>
            <Link href="/recrutador">Recrutador</Link>
            <Link href="/privacidade">Privacidade</Link>
          </nav>
          <p>
            Projeto de portfólio. Modo demonstração: análise por regras, sem IA. Os casos de exemplo são
            fictícios.
          </p>
          <p className="rodape__creditos">
            Imagens de acervo, via Wikimedia Commons:{" "}
            <a href="https://commons.wikimedia.org/wiki/File:Carimbo,_Acervo_do_Museu_Paulista_da_USP_(2).jpg">
              “Carimbo”, Acervo do Museu Paulista da USP
            </a>{" "}
            (CC BY-SA 4.0);{" "}
            <a href="https://commons.wikimedia.org/wiki/File:Rubber_stamps_state_retail_stores_Czechia_1984.jpg">
              “Rubber stamps state retail stores Czechia 1984”, Jan Pešula
            </a>{" "}
            (CC0);{" "}
            <a href="https://commons.wikimedia.org/wiki/File:Olympia_Simplex.jpg">
              “Olympia Simplex”, Sammlung der Medien und Wissenschaft
            </a>{" "}
            (CC BY 4.0);{" "}
            <a href="https://commons.wikimedia.org/wiki/File:The_very_first_wikipassport_-_the_stamp.webm">
              “The very first wikipassport – the stamp”, Ysogo
            </a>{" "}
            (CC BY-SA 4.0, vídeo).
          </p>
        </div>
      </footer>
    </div>
  );
}
