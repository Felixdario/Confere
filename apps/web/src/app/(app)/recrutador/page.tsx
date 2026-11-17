"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Carregando, Erro } from "@/componentes/moldura";
import { api, type ProcessoDetalhe, type ProcessoResumo } from "@/lib/api";
import { useExigirSessao } from "@/lib/sessao";
import { data } from "@/lib/textos";

import "./recrutador.css";

export default function Recrutador() {
  const eu = useExigirSessao();
  const router = useRouter();
  const cliente = useQueryClient();
  const q = useQuery({ queryKey: ["processos"], queryFn: () => api<ProcessoResumo[]>("/processos"), enabled: !!eu.data });

  const [titulo, setTitulo] = useState("");
  const [vaga, setVaga] = useState("");
  const [base, setBase] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const criar = useMutation({
    mutationFn: () =>
      api<ProcessoDetalhe>("/processos", {
        metodo: "POST",
        corpo: { titulo: titulo.trim() || null, vaga_texto: vaga, declaro_base_legal: base },
      }),
    onSuccess: async (p) => {
      await cliente.invalidateQueries({ queryKey: ["processos"] });
      router.push(`/recrutador/${p.id}`);
    },
    onError: (e) => setErro(e.message),
  });

  function enviar(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    if (vaga.trim().length < 40) return setErro("Cole a descrição da vaga com a lista de requisitos.");
    if (!base) return setErro("Confirme a base legal antes de tratar currículos de outras pessoas.");
    criar.mutate();
  }

  if (!eu.data || q.isPending) return <Carregando texto="Abrindo as triagens…" />;
  if (q.isError) return <Erro erro={q.error} tentar={() => void q.refetch()} />;

  return (
    <>
      <title>Recrutador · Confere</title>
      <div className="cabeca-tela">
        <div>
          <h1 className="titulo-tela">Recrutador</h1>
          <p className="subtitulo-tela">
            Triagem anonimizada: até 20 currículos por vaga, sem nome, foto, idade, gênero ou endereço. A decisão é
            sempre sua, com justificativa.
          </p>
        </div>
      </div>

      <div className="recrutador">
        <section aria-labelledby="processos-titulo">
          <h2 id="processos-titulo" className="bloco__titulo">
            Triagens
          </h2>
          {q.data.length === 0 ? (
            <p className="vazio">Nenhuma triagem ainda. Crie a primeira ao lado com a descrição da vaga.</p>
          ) : (
            <table className="tabela">
              <thead>
                <tr>
                  <th scope="col">Triagem</th>
                  <th scope="col" className="direita">
                    Currículos
                  </th>
                  <th scope="col" className="direita">
                    Criada em
                  </th>
                </tr>
              </thead>
              <tbody>
                {q.data.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <Link href={`/recrutador/${p.id}`} className="recrutador__link">
                        {p.titulo}
                      </Link>
                      <span className="requisitos__tipo">{p.vaga.titulo}</span>
                    </td>
                    <td className="numeros">
                      {p.candidatos} de {p.limite_candidatos}
                    </td>
                    <td className="numeros">{data(p.criado_em)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="recrutador__nova" aria-labelledby="nova-triagem">
          <h2 id="nova-triagem" className="bloco__titulo">
            Nova triagem
          </h2>
          <form className="formulario" onSubmit={enviar} noValidate>
            <div className="campo">
              <label htmlFor="tri-titulo">Nome da triagem (opcional)</label>
              <input id="tri-titulo" maxLength={200} value={titulo} onChange={(e) => setTitulo(e.currentTarget.value)} />
            </div>
            <div className="campo">
              <label htmlFor="tri-vaga">Vaga</label>
              <textarea
                id="tri-vaga"
                rows={8}
                value={vaga}
                onChange={(e) => setVaga(e.currentTarget.value)}
                placeholder="Cole a descrição da vaga, com os requisitos"
              />
            </div>
            <label className="marcar">
              <input type="checkbox" checked={base} onChange={(e) => setBase(e.currentTarget.checked)} />
              <span>
                Declaro que tenho base legal (LGPD) para tratar estes currículos, como o consentimento das pessoas
                candidatas para este processo.
              </span>
            </label>
            {erro && (
              <p className="formulario__erro" role="alert">
                {erro}
              </p>
            )}
            <button type="submit" className="botao" disabled={criar.isPending}>
              {criar.isPending ? "Criando…" : "Criar triagem"}
            </button>
          </form>
        </section>
      </div>
    </>
  );
}
