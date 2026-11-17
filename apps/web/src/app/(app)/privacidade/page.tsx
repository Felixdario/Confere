"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Confirmar } from "@/componentes/confirmar";
import { Carregando, Erro } from "@/componentes/moldura";
import { api, esquecerCsrf, type Esquemas, type Privacidade } from "@/lib/api";
import { useEu } from "@/lib/sessao";
import { data } from "@/lib/textos";

import "./privacidade.css";

const NOMES_APAGADOS: Record<string, string> = {
  analises: "análises",
  curriculo_versoes: "versões de currículo",
  curriculos: "currículos",
  usuarios: "conta",
  vagas: "vagas",
  processos: "triagens",
  candidatos: "candidatos",
  decisoes: "decisões",
  consentimentos: "consentimentos",
  sessoes: "sessões",
};

export default function PaginaPrivacidade() {
  const eu = useEu();
  const cliente = useQueryClient();
  const q = useQuery({ queryKey: ["privacidade"], queryFn: () => api<Privacidade>("/privacidade") });
  const [apagado, setApagado] = useState<Esquemas["DadosApagados"] | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  if (q.isPending) return <Carregando />;
  if (q.isError) return <Erro erro={q.error} tentar={() => void q.refetch()} />;
  const p = q.data;

  async function apagar() {
    setErro(null);
    try {
      const r = await api<Esquemas["DadosApagados"]>("/eu/dados", { metodo: "DELETE" });
      esquecerCsrf();
      cliente.removeQueries({ predicate: (x) => x.queryKey[0] !== "privacidade" });
      cliente.setQueryData(["eu"], null);
      setApagado(r);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível apagar.");
    }
  }

  return (
    <>
      <title>Privacidade · Confere</title>
      <div className="cabeca-tela">
        <div>
          <h1 className="titulo-tela">Privacidade</h1>
          <p className="subtitulo-tela">
            Arquivos e textos ficam <strong className="numeros">{p.retencao_dias} dias</strong> e depois são apagados
            sozinhos.
          </p>
        </div>
      </div>

      <div className="privacidade">
        <section aria-labelledby="guardamos">
          <h2 id="guardamos" className="bloco__titulo">
            O que guardamos
          </h2>
          <table className="tabela">
            <thead>
              <tr>
                <th scope="col">Dado</th>
                <th scope="col">Por quanto tempo</th>
              </tr>
            </thead>
            <tbody>
              {p.o_que_guardamos.map((g) => (
                <tr key={g.dado}>
                  <td>{g.dado}</td>
                  <td>{g.por_quanto_tempo}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h2 className="bloco__titulo bloco">O que nunca guardamos</h2>
          <ul className="lista-simples">
            {p.o_que_nunca_guardamos.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>

          <h2 className="bloco__titulo bloco">O que vai para a IA</h2>
          <p className="privacidade__texto">{p.o_que_vai_para_a_ia}</p>
        </section>

        <section className="privacidade__lado" aria-labelledby="apagar">
          <h2 id="apagar" className="bloco__titulo">
            Apagar meus dados
          </h2>
          <p className="privacidade__texto">{p.como_apagar}</p>

          {apagado ? (
            <div className="privacidade__apagado" role="status">
              <strong>{apagado.mensagem}</strong>
              <ul className="lista-simples numeros">
                {Object.entries(apagado.apagado)
                  .filter(([, n]) => n > 0)
                  .map(([k, n]) => (
                    <li key={k}>
                      {n} {NOMES_APAGADOS[k] ?? k.replaceAll("_", " ")}
                    </li>
                  ))}
                <li>{apagado.arquivos} arquivos do disco</li>
              </ul>
              <Link href="/">Voltar ao início</Link>
            </div>
          ) : eu.data ? (
            <>
              <p className="nota-rodape">
                Conta {eu.data.email}, criada em {data(eu.data.criado_em)}.
              </p>
              <Confirmar
                gatilho="Apagar meus dados"
                titulo="Apagar todos os seus dados?"
                confirmar="Apagar tudo agora"
                perigo
                aoConfirmar={apagar}
              >
                <p>
                  A conta, os currículos, as vagas, as análises e as triagens são apagados na hora, inclusive uma análise em
                  andamento. A sessão é encerrada.
                </p>
                <p>
                  <strong>Não há como desfazer.</strong>
                </p>
              </Confirmar>
              {erro && (
                <p className="privacidade__erro" role="alert">
                  {erro}
                </p>
              )}
            </>
          ) : eu.data === null ? (
            <p>
              <Link href="/entrar?volta=/privacidade">Entre na conta</Link> para apagar seus dados.
            </p>
          ) : null}

          <h2 className="bloco__titulo bloco">Consentimento</h2>
          <p className="privacidade__texto">{p.texto_consentimento}</p>
          <p className="nota-rodape">Versão do texto: {p.versao_texto}.</p>
        </section>
      </div>
    </>
  );
}
