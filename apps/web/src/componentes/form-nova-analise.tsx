"use client";

import { useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, type DragEvent, type FormEvent } from "react";

import { api, ErroApi, type Esquemas } from "@/lib/api";
import {
  guardarRascunho,
  problemaDoArquivo,
  retirarRascunho,
  tamanhoLegivel,
  TIPOS_ACEITOS,
} from "@/lib/arquivo-pendente";

import "./form-nova-analise.css";

/**
 * A caixa de nova análise: currículo (arquivo ou texto colado) + vaga + Analisar. A mesma peça
 * serve à tela /nova e ao fim da landing. Sem sessão, guarda o rascunho e leva ao login.
 */
export function FormNovaAnalise({
  compacto = false,
  curriculoId,
  vaga: vagaFixa,
}: {
  compacto?: boolean;
  /** Nova versão de um currículo já enviado. */
  curriculoId?: string | undefined;
  /** Mesma vaga de uma análise anterior (para comparar versões). */
  vaga?: { id: string; titulo: string } | undefined;
}) {
  const router = useRouter();
  const cliente = useQueryClient();
  const ids = { arquivo: useId(), texto: useId(), vaga: useId(), dicaArquivo: useId(), dicaVaga: useId(), erro: useId() };
  const entrada = useRef<HTMLInputElement>(null);

  const [modo, setModo] = useState<"arquivo" | "texto">("arquivo");
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [texto, setTexto] = useState("");
  const [vaga, setVaga] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [arrastando, setArrastando] = useState(false);

  useEffect(() => {
    const r = retirarRascunho();
    if (!r) return;
    // Rascunho vindo da landing ou do login: restaura uma vez, depois da montagem.
    queueMicrotask(() => {
      if (r.arquivo) {
        setArquivo(r.arquivo);
        setModo("arquivo");
      } else if (r.texto) {
        setTexto(r.texto);
        setModo("texto");
      }
      if (r.vaga) setVaga(r.vaga);
    });
  }, []);

  function escolher(a: File | undefined | null) {
    if (!a) return;
    const p = problemaDoArquivo(a);
    setErro(p);
    setArquivo(p ? null : a);
  }

  function soltar(e: DragEvent) {
    e.preventDefault();
    setArrastando(false);
    escolher(e.dataTransfer.files[0]);
  }

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    const temCurriculo = modo === "arquivo" ? arquivo : texto.trim();
    if (!temCurriculo) {
      setErro(modo === "arquivo" ? "Escolha o arquivo do currículo, ou cole o texto." : "Cole o texto do currículo.");
      return;
    }
    if (!vagaFixa && vaga.trim().length < 40) {
      setErro("Cole a descrição da vaga com a lista de requisitos.");
      return;
    }
    const corpo = new FormData();
    if (modo === "arquivo" && arquivo) corpo.append("arquivo", arquivo);
    else corpo.append("texto", texto);
    if (vagaFixa) corpo.append("vaga_id", vagaFixa.id);
    else corpo.append("vaga_texto", vaga);
    if (curriculoId) corpo.append("curriculo_id", curriculoId);

    setEnviando(true);
    try {
      const criada = await api<Esquemas["AnaliseCriada"]>("/analises", { metodo: "POST", corpo });
      void cliente.invalidateQueries({ queryKey: ["analises"] });
      router.push(`/analises/${criada.id}`);
    } catch (err) {
      setEnviando(false);
      if (err instanceof ErroApi && err.status === 401) {
        guardarRascunho({ arquivo: modo === "arquivo" ? arquivo : null, texto: modo === "texto" ? texto : "", vaga });
        router.push("/entrar?volta=/nova");
        return;
      }
      setErro(err instanceof Error ? err.message : "Não foi possível enviar. Tente de novo.");
    }
  }

  return (
    <form className={clsx("nova", compacto && "nova--compacta")} onSubmit={enviar} noValidate data-ui>
      <fieldset className="nova__bloco">
        <legend className="nova__rotulo">Currículo</legend>
        <div className="nova__modos" role="group" aria-label="Como enviar o currículo">
          <button type="button" aria-pressed={modo === "arquivo"} onClick={() => setModo("arquivo")}>
            Arquivo
          </button>
          <button type="button" aria-pressed={modo === "texto"} onClick={() => setModo("texto")}>
            Colar texto
          </button>
        </div>

        {modo === "arquivo" ? (
          <div
            className={clsx("nova__soltar", arrastando && "nova__soltar--ativo", arquivo && "nova__soltar--cheio")}
            onDragOver={(e) => {
              e.preventDefault();
              setArrastando(true);
            }}
            onDragLeave={() => setArrastando(false)}
            onDrop={soltar}
          >
            <input
              ref={entrada}
              id={ids.arquivo}
              type="file"
              accept={TIPOS_ACEITOS}
              className="so-leitor"
              aria-describedby={ids.dicaArquivo}
              onChange={(e) => escolher(e.currentTarget.files?.[0])}
            />
            {arquivo ? (
              <p className="nova__arquivo">
                <span className="nova__nome-arquivo">{arquivo.name}</span>
                <span className="numeros"> · {tamanhoLegivel(arquivo.size)}</span>
              </p>
            ) : (
              <p className="nova__vazio">Arraste o arquivo para cá ou</p>
            )}
            <label htmlFor={ids.arquivo} className="botao botao--secundario">
              {arquivo ? "Trocar arquivo" : "Escolher arquivo"}
            </label>
          </div>
        ) : (
          <>
            <label htmlFor={ids.texto} className="so-leitor">
              Texto do currículo
            </label>
            <textarea
              id={ids.texto}
              className="nova__campo nova__campo--documento"
              rows={compacto ? 5 : 10}
              value={texto}
              onChange={(e) => setTexto(e.currentTarget.value)}
              placeholder="Cole aqui o texto do currículo"
              aria-describedby={ids.dicaArquivo}
            />
          </>
        )}
        <p id={ids.dicaArquivo} className="nova__dica">
          PDF ou DOCX até 5 MB e 20 páginas, ou o texto colado. Nome, contatos e documentos são removidos
          antes da leitura.
        </p>
      </fieldset>

      {vagaFixa ? (
        <div className="nova__bloco">
          <p className="nova__rotulo">Vaga</p>
          <p className="nova__arquivo">
            <span className="nova__nome-arquivo">{vagaFixa.titulo}</span>, a mesma da análise anterior.
          </p>
        </div>
      ) : (
      <div className="nova__bloco">
        <label htmlFor={ids.vaga} className="nova__rotulo">
          Vaga
        </label>
        <textarea
          id={ids.vaga}
          className="nova__campo nova__campo--documento"
          rows={compacto ? 5 : 12}
          value={vaga}
          onChange={(e) => setVaga(e.currentTarget.value)}
          placeholder="Cole a descrição da vaga, com os requisitos obrigatórios e desejáveis"
          aria-describedby={ids.dicaVaga}
        />
        <p id={ids.dicaVaga} className="nova__dica">
          Copie a descrição inteira: os requisitos saem da lista da vaga.
        </p>
      </div>
      )}

      {erro && (
        <p id={ids.erro} className="nova__erro" role="alert">
          {erro}
        </p>
      )}

      <div className="nova__acoes">
        <button type="submit" className="botao" disabled={enviando} aria-describedby={erro ? ids.erro : undefined}>
          {enviando ? "Enviando…" : "Analisar"}
        </button>
        <p className="selo-modo">
          <strong>Modo demonstração:</strong> análise por regras, sem IA.
        </p>
      </div>
    </form>
  );
}
