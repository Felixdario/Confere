"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { use, useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Carimbo } from "@/componentes/carimbo";
import { Confirmar } from "@/componentes/confirmar";
import { Carregando, Erro } from "@/componentes/moldura";
import { api, BASE, type CandidatoDetalhe, type CandidatoRanking, type Esquemas, type ProcessoDetalhe } from "@/lib/api";
import { problemaDoArquivo, TIPOS_ACEITOS } from "@/lib/arquivo-pendente";
import { useExigirSessao } from "@/lib/sessao";
import { dataHora, fraseDoAviso, ROTULO_DO_TIPO } from "@/lib/textos";

import "../../analises/[id]/analise.css";
import "../recrutador.css";

const DECISAO = { avancar: "Avançar", nao_avancar: "Não avançar", pendente: "Pendente" } as const;
type Decisao = keyof typeof DECISAO;

function obrigatorios(c: CandidatoRanking) {
  const o = c.requisitos.filter((r) => r.tipo === "obrigatorio");
  return { atende: o.filter((r) => r.status === "atende").length, total: o.length };
}

function EnviarCurriculos({ processo, aoEnviar }: { processo: ProcessoDetalhe; aoEnviar: () => void }) {
  const [enviando, setEnviando] = useState<string | null>(null);
  const vagas = processo.limite_candidatos - processo.candidatos;

  async function enviar(arquivos: FileList | null) {
    if (!arquivos?.length) return;
    const lista = Array.from(arquivos).slice(0, vagas);
    if (arquivos.length > vagas) toast.warning(`Só cabem mais ${vagas}; os outros ficaram de fora.`);
    for (const [i, a] of lista.entries()) {
      const p = problemaDoArquivo(a);
      if (p) {
        toast.error(`${a.name}: ${p}`);
        continue;
      }
      setEnviando(`Enviando ${i + 1} de ${lista.length}…`);
      const corpo = new FormData();
      corpo.append("arquivo", a);
      try {
        await api<Esquemas["CandidatoCriado"]>(`/processos/${processo.id}/candidatos`, { metodo: "POST", corpo });
      } catch (e) {
        toast.error(`${a.name}: ${e instanceof Error ? e.message : "não foi enviado"}`);
      }
    }
    setEnviando(null);
    aoEnviar();
  }

  if (vagas <= 0) return <p className="nota-rodape">A triagem chegou ao limite de {processo.limite_candidatos} currículos.</p>;
  return (
    <div className="envio-lote">
      <input
        id="lote"
        type="file"
        multiple
        accept={TIPOS_ACEITOS}
        className="so-leitor"
        aria-describedby="lote-dica"
        onChange={(e) => void enviar(e.currentTarget.files)}
        disabled={!!enviando}
      />
      <label htmlFor="lote" className="botao" aria-disabled={!!enviando}>
        {enviando ?? "Enviar currículos"}
      </label>
      <p id="lote-dica" className="nota-rodape">
        PDF ou DOCX, até 5 MB cada. Cabem mais {vagas}.
      </p>
    </div>
  );
}

function Detalhe({ processoId, candidatoId, aoMudar }: { processoId: string; candidatoId: string; aoMudar: () => void }) {
  const cliente = useQueryClient();
  const q = useQuery({
    queryKey: ["candidato", processoId, candidatoId],
    queryFn: () => api<CandidatoDetalhe>(`/processos/${processoId}/candidatos/${candidatoId}`),
  });
  const [decisao, setDecisao] = useState<Decisao>("pendente");
  const [justificativa, setJustificativa] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [arquivo, setArquivo] = useState<string | null>(null);

  useEffect(() => {
    const atual = q.data?.decisao?.decisao;
    if (atual) queueMicrotask(() => setDecisao(atual));
  }, [q.data?.decisao?.decisao]);

  if (q.isPending) return <Carregando texto="Abrindo o candidato…" />;
  if (q.isError) return <Erro erro={q.error} tentar={() => void q.refetch()} />;
  const c = q.data;

  async function registrar(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    if (justificativa.trim().length < 3) return setErro("Escreva a justificativa da decisão.");
    setSalvando(true);
    try {
      await api(`/processos/${processoId}/candidatos/${candidatoId}/decisoes`, {
        metodo: "POST",
        corpo: { decisao, justificativa },
      });
      setJustificativa("");
      toast.success(`Decisão registrada: ${DECISAO[decisao].toLowerCase()}.`);
      await cliente.invalidateQueries({ queryKey: ["candidato", processoId, candidatoId] });
      aoMudar();
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Não foi possível registrar.");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="candidato">
      <div className="candidato__cabeca">
        <h2 className="titulo-tela">{c.rotulo}</h2>
        <p className="candidato__nota numeros" aria-label={c.nota !== null ? `Nota ${c.nota}` : "Sem nota"}>
          {c.nota ?? "—"}
        </p>
      </div>
      {c.decomposicao && <p className="nota-rodape numeros">{c.decomposicao}</p>}

      {c.avisos.length > 0 &&
        c.avisos.map((v, i) => {
          const f = fraseDoAviso(v.tipo, v.motivo);
          return (
            <div key={i} className="aviso bloco-curto">
              <strong>{f.titulo}</strong>
              <p>{f.feito}</p>
            </div>
          );
        })}

      <section className="bloco-curto" aria-labelledby="cand-req">
        <h3 id="cand-req" className="bloco__titulo">
          Requisitos
        </h3>
        <table className="tabela requisitos">
          <thead>
            <tr>
              <th scope="col">Requisito</th>
              <th scope="col">Estado</th>
              <th scope="col">Trecho</th>
            </tr>
          </thead>
          <tbody>
            {c.tabela.map((r) => (
              <tr key={`${r.tipo}-${r.descricao}`} data-estado={r.status}>
                <td className="requisitos__nome">
                  <span>{r.descricao}</span>
                  <span className="requisitos__tipo">{ROTULO_DO_TIPO[r.tipo]}</span>
                </td>
                <td>
                  <Carimbo estado={r.status} valor={r.valor} />
                </td>
                <td className="requisitos__trecho">
                  {r.evidencia ? <q className="trecho">{r.evidencia}</q> : <span className="requisitos__falta">Nenhum trecho.</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="bloco-curto" aria-labelledby="cand-decisao">
        <h3 id="cand-decisao" className="bloco__titulo">
          Decisão
        </h3>
        <form className="formulario" onSubmit={registrar}>
          <fieldset className="decisao">
            <legend className="so-leitor">Decisão</legend>
            {(Object.keys(DECISAO) as Decisao[]).map((d) => (
              <label key={d} className={clsx("decisao__opcao", decisao === d && "decisao__opcao--ativa")}>
                <input type="radio" name="decisao" value={d} checked={decisao === d} onChange={() => setDecisao(d)} />
                {DECISAO[d]}
              </label>
            ))}
          </fieldset>
          <div className="campo">
            <label htmlFor="justificativa">Justificativa</label>
            <textarea
              id="justificativa"
              rows={3}
              value={justificativa}
              onChange={(e) => setJustificativa(e.currentTarget.value)}
              placeholder="Por que esta decisão, com base nos requisitos"
            />
          </div>
          {erro && (
            <p className="formulario__erro" role="alert">
              {erro}
            </p>
          )}
          <button type="submit" className="botao" disabled={salvando}>
            {salvando ? "Registrando…" : "Registrar decisão"}
          </button>
        </form>
        {c.decisoes.length > 0 && (
          <ol className="decisoes">
            {c.decisoes.map((d) => (
              <li key={d.id}>
                <span className="numeros">{dataHora(d.criado_em)}</span>
                <strong>{DECISAO[d.decisao]}</strong>
                <span>{d.justificativa ?? "justificativa apagada pela retenção"}</span>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="bloco-curto" aria-labelledby="cand-identidade">
        <h3 id="cand-identidade" className="bloco__titulo">
          Identidade
        </h3>
        {c.identidade_revelada_em || arquivo ? (
          <p>
            Revelada em {c.identidade_revelada_em ? dataHora(c.identidade_revelada_em) : "agora"}.{" "}
            <a href={arquivo ?? `${BASE}/processos/${processoId}/candidatos/${candidatoId}/arquivo`}>Baixar o arquivo original</a>
          </p>
        ) : (
          <>
            <p className="nota-rodape">
              A visão fica anonimizada. Revele só quando precisar entrar em contato; a ação fica registrada.
            </p>
            <Confirmar
              gatilho="Revelar identidade"
              titulo={`Revelar a identidade de ${c.rotulo}?`}
              confirmar="Revelar e registrar"
              aoConfirmar={async () => {
                try {
                  const r = await api<Esquemas["Revelacao"]>(`/processos/${processoId}/candidatos/${candidatoId}/revelar`, {
                    metodo: "POST",
                  });
                  setArquivo(r.arquivo_url ? `${BASE}${r.arquivo_url}` : null);
                  await cliente.invalidateQueries({ queryKey: ["candidato", processoId, candidatoId] });
                } catch (e) {
                  toast.error(e instanceof Error ? e.message : "Não foi possível revelar.");
                }
              }}
            >
              <p>O arquivo original fica liberado para download, com nome e contatos.</p>
              <p>Quem revelou e quando fica no registro da triagem. Não dá para voltar à visão anônima deste candidato.</p>
            </Confirmar>
          </>
        )}
      </section>
    </div>
  );
}

export default function Triagem({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const eu = useExigirSessao();
  const [selecionado, setSelecionado] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["processo", id],
    queryFn: () => api<ProcessoDetalhe>(`/processos/${id}`),
    enabled: !!eu.data,
    refetchInterval: (consulta) =>
      consulta.state.data?.ranking.some((c) => c.status === "na_fila" || c.status === "processando") ? 2500 : false,
  });

  if (!eu.data || q.isPending) return <Carregando texto="Abrindo a triagem…" />;
  if (q.isError) return <Erro erro={q.error} tentar={() => void q.refetch()} />;
  const p = q.data;
  const prontos = p.ranking.filter((c) => c.status === "concluida");
  const todos = prontos.filter((c) => {
    const o = obrigatorios(c);
    return o.total > 0 && o.atende === o.total;
  }).length;
  const escolhido = selecionado ?? prontos[0]?.id ?? null;

  return (
    <>
      <title>{`${p.titulo} · Recrutador · Confere`}</title>
      <div className="cabeca-tela">
        <div>
          <h1 className="titulo-tela">{p.titulo}</h1>
          <p className="subtitulo-tela numeros">
            {p.ranking.length === 0
              ? "Nenhum currículo ainda."
              : `${todos} de ${p.ranking.length} atendem todos os obrigatórios.`}
          </p>
        </div>
        <EnviarCurriculos processo={p} aoEnviar={() => void q.refetch()} />
      </div>
      <p className="nota-rodape triagem__aviso">{p.aviso}</p>

      {p.ranking.length === 0 ? (
        <div className="vazio">
          <p>Envie os currículos da vaga “{p.vaga.titulo}”. Cada um aparece como “Candidato A”, “Candidato B”…</p>
        </div>
      ) : (
        <div className="triagem">
          <div className="rolagem-x">
            <table className="tabela ranking">
              <caption className="so-leitor">Candidatos, do maior para o menor nota</caption>
              <thead>
                <tr>
                  <th scope="col">Candidato</th>
                  <th scope="col" className="direita">
                    Nota
                  </th>
                  <th scope="col" className="direita">
                    Obrigatórios
                  </th>
                  <th scope="col">Decisão</th>
                </tr>
              </thead>
              <tbody>
                {p.ranking.map((c) => {
                  const o = obrigatorios(c);
                  const pronto = c.status === "concluida";
                  return (
                    <tr key={c.id} className={clsx(escolhido === c.id && "ranking__linha--ativa")}>
                      <td>
                        <button
                          type="button"
                          className="ranking__nome"
                          onClick={() => setSelecionado(c.id)}
                          disabled={!pronto}
                          aria-pressed={escolhido === c.id}
                        >
                          {c.rotulo}
                        </button>
                      </td>
                      <td className="numeros ranking__nota">{pronto ? c.nota : c.status === "erro" ? "erro" : "…"}</td>
                      <td className="numeros">{pronto ? `${o.atende} de ${o.total}` : "—"}</td>
                      <td>{c.decisao ? DECISAO[c.decisao.decisao] : pronto ? "sem decisão" : "analisando"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="triagem__detalhe">
            {escolhido ? (
              <Detalhe key={escolhido} processoId={id} candidatoId={escolhido} aoMudar={() => void q.refetch()} />
            ) : (
              <p className="estado">Os currículos ainda estão sendo analisados.</p>
            )}
          </div>
        </div>
      )}
    </>
  );
}
