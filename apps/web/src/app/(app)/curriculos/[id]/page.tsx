"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, use } from "react";

import { Carimbo } from "@/componentes/carimbo";
import { Carregando, Erro } from "@/componentes/moldura";
import { api, type Comparacao } from "@/lib/api";
import { useExigirSessao } from "@/lib/sessao";
import { data, ROTULO_DO_TIPO } from "@/lib/textos";

import "../../analises/[id]/analise.css";
import "./comparacao.css";

function Comparar({ id }: { id: string }) {
  const eu = useExigirSessao();
  const busca = useSearchParams();
  const router = useRouter();
  const vaga = busca.get("vaga") ?? "";
  const de = busca.get("de");
  const para = busca.get("para");
  const q = useQuery({
    queryKey: ["comparacao", id, vaga, de, para],
    queryFn: () =>
      api<Comparacao>(
        `/curriculos/${id}/comparacao?vaga=${encodeURIComponent(vaga)}${de ? `&de=${de}` : ""}${para ? `&para=${para}` : ""}`,
      ),
    enabled: !!eu.data && !!vaga,
  });

  if (!vaga) return <Erro erro={new Error("Escolha a vaga no histórico para comparar as versões.")} />;
  if (!eu.data || q.isPending) return <Carregando texto="Comparando as versões…" />;
  if (q.isError) return <Erro erro={q.error} tentar={() => void q.refetch()} />;
  const c = q.data;

  const trocar = (campo: "de" | "para", valor: string) => {
    const p = new URLSearchParams(busca.toString());
    p.set(campo, valor);
    router.replace(`?${p.toString()}`);
  };

  return (
    <>
      <title>{`Comparação · ${c.vaga.titulo} · Confere`}</title>
      <div className="cabeca-tela">
        <div>
          <h1 className="titulo-tela">{c.vaga.titulo}</h1>
          <p className="subtitulo-tela">{c.frase}</p>
        </div>
        <div className="cabeca-tela__acoes">
          <Link className="botao botao--secundario" href={`/analises/${c.para.analise_id}`}>
            Ver o resultado da versão {c.para.versao}
          </Link>
        </div>
      </div>

      <section className="versus" aria-label="Notas das duas versões">
        <div className="versus__lado versus__lado--antes">
          <label htmlFor="cmp-de" className="versus__rotulo">
            Versão anterior
          </label>
          <select id="cmp-de" value={c.de.versao} onChange={(e) => trocar("de", e.currentTarget.value)}>
            {c.versoes.map((v) => (
              <option key={v.versao} value={v.versao} disabled={v.versao === c.para.versao}>
                Versão {v.versao} · {data(v.criado_em)}
              </option>
            ))}
          </select>
          <p className="versus__nota numeros">{c.de.nota}</p>
        </div>
        <p className="versus__seta numeros" role="img" aria-label={`Diferença de ${c.diferenca} pontos`}>
          {c.diferenca > 0 ? `+${c.diferenca}` : c.diferenca < 0 ? `−${Math.abs(c.diferenca)}` : "0"}
        </p>
        <div className="versus__lado">
          <label htmlFor="cmp-para" className="versus__rotulo">
            Versão nova
          </label>
          <select id="cmp-para" value={c.para.versao} onChange={(e) => trocar("para", e.currentTarget.value)}>
            {c.versoes.map((v) => (
              <option key={v.versao} value={v.versao} disabled={v.versao === c.de.versao}>
                Versão {v.versao} · {data(v.criado_em)}
              </option>
            ))}
          </select>
          <p className="versus__nota numeros">{c.para.nota}</p>
        </div>
      </section>

      <section className="bloco" aria-labelledby="mudancas-titulo">
        <h2 id="mudancas-titulo" className="bloco__titulo">
          O que mudou, requisito por requisito
        </h2>
        {c.mudancas.length === 0 ? (
          <p>Nenhum requisito mudou de estado entre as duas versões.</p>
        ) : (
          <div className="rolagem-x" role="region" aria-label="Mudanças por requisito" tabIndex={0}>
            <table className="tabela mudancas">
              <thead>
                <tr>
                  <th scope="col">Requisito</th>
                  <th scope="col">Versão {c.de.versao}</th>
                  <th scope="col" aria-label="mudou para" />
                  <th scope="col">Versão {c.para.versao}</th>
                </tr>
              </thead>
              <tbody>
                {c.mudancas.map((m) => (
                  <tr key={m.requisito}>
                    <td>
                      <span className="mudancas__nome">{m.requisito}</span>
                      <span className="requisitos__tipo">{ROTULO_DO_TIPO[m.tipo]}</span>
                    </td>
                    <td className="mudancas__antes">{m.de ? <Carimbo estado={m.de} /> : "não existia"}</td>
                    <td aria-hidden="true">→</td>
                    <td>{m.para ? <Carimbo estado={m.para} /> : "não existe mais"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

export default function PaginaComparacao({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <Suspense>
      <Comparar id={id} />
    </Suspense>
  );
}
