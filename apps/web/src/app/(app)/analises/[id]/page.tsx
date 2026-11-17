"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use, useCallback, useState } from "react";

import { Carregando, Erro } from "@/componentes/moldura";
import { api, type AnaliseDetalhe } from "@/lib/api";
import { useExigirSessao } from "@/lib/sessao";

import "./analise.css";
import { Progresso } from "./progresso";
import { Resultado } from "./resultado";

export default function PaginaAnalise({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const eu = useExigirSessao();
  const [erroDoFluxo, setErroDoFluxo] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["analise", id],
    queryFn: () => api<AnaliseDetalhe>(`/analises/${id}`),
    enabled: !!eu.data,
  });

  const { refetch } = q;
  const aoTerminar = useCallback(
    (fim: { status: "concluida" } | { status: "erro"; mensagem: string }) => {
      if (fim.status === "erro") setErroDoFluxo(fim.mensagem);
      void refetch();
    },
    [refetch],
  );

  if (!eu.data || q.isPending) return <Carregando texto="Abrindo a análise…" />;
  if (q.isError) return <Erro erro={q.error} tentar={() => void q.refetch()} />;
  const a = q.data;

  if (a.status === "erro" || erroDoFluxo) {
    return (
      <>
        <title>Análise com erro · Confere</title>
        <h1 className="titulo-tela">{a.vaga.titulo}</h1>
        <div className="aviso analise-erro" role="alert">
          <strong>A análise não terminou.</strong>
          <p>{a.erro?.mensagem ?? erroDoFluxo}</p>
        </div>
        <p className="bloco">
          <Link className="botao" href="/nova">
            Tentar com outro arquivo
          </Link>
        </p>
      </>
    );
  }

  if (a.status !== "concluida") {
    return (
      <>
        <title>Analisando · Confere</title>
        <div className="cabeca-tela">
          <div>
            <h1 className="titulo-tela">{a.vaga.titulo}</h1>
            <p className="subtitulo-tela">Conferindo o currículo contra a vaga, etapa por etapa.</p>
          </div>
        </div>
        <Progresso analise={a} aoTerminar={aoTerminar} />
      </>
    );
  }

  return (
    <>
      <title>{`Nota ${a.nota ?? ""} · ${a.vaga.titulo} · Confere`}</title>
      <Resultado a={a} />
    </>
  );
}
