"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { useEu, useSair } from "@/lib/sessao";

import { CarimboTexto } from "./carimbo";

const DESTINOS = [
  { href: "/nova", rotulo: "Nova análise" },
  { href: "/historico", rotulo: "Histórico" },
  { href: "/recrutador", rotulo: "Recrutador" },
  { href: "/privacidade", rotulo: "Privacidade" },
];

/**
 * O app no estilo `framed-sheet`: moldura em L (barra lateral e barra de cima no mesmo tom, sem
 * fio) e o trabalho numa folha branca com 8 px de recuo. O selo do modo fica sempre na barra de cima.
 */
export function Moldura({ children }: { children: ReactNode }) {
  const caminho = usePathname();
  const eu = useEu();
  const sair = useSair();
  const [menuAberto, setMenuAberto] = useState(false);

  useEffect(() => {
    queueMicrotask(() => setMenuAberto(false));
  }, [caminho]);

  const ativo = (href: string) =>
    caminho === href ||
    caminho.startsWith(`${href}/`) ||
    (href === "/historico" && (caminho.startsWith("/analises") || caminho.startsWith("/curriculos")));

  return (
    <div className={clsx("moldura", menuAberto && "moldura--menu")}>
      <a href="#folha" className="pular">
        Pular para o conteúdo
      </a>
      <aside className="lateral" aria-label="Navegação">
        <Link href="/" className="lateral__marca" aria-label="Confere, página inicial">
          <CarimboTexto estado="neutro">Confere</CarimboTexto>
        </Link>
        <nav className="lateral__nav" id="menu-principal">
          {DESTINOS.map((d) => (
            <Link
              key={d.href}
              href={d.href}
              className={clsx("lateral__item", ativo(d.href) && "lateral__item--ativo")}
              aria-current={ativo(d.href) ? "page" : undefined}
            >
              {d.rotulo}
            </Link>
          ))}
        </nav>
        <div className="lateral__pe">
          {eu.data ? (
            <>
              <p className="lateral__conta" title={eu.data.email}>
                {eu.data.email}
              </p>
              <button type="button" className="lateral__sair" onClick={sair}>
                Sair
              </button>
            </>
          ) : eu.data === null ? (
            <Link href={`/entrar?volta=${encodeURIComponent(caminho)}`} className="lateral__item">
              Entrar
            </Link>
          ) : null}
        </div>
      </aside>

      <header className="topo">
        <button
          type="button"
          className="topo__menu"
          aria-expanded={menuAberto}
          aria-controls="menu-principal"
          onClick={() => setMenuAberto((v) => !v)}
        >
          {menuAberto ? "Fechar" : "Menu"}
        </button>
        <Link href="/" className="topo__marca" aria-label="Confere, página inicial">
          <CarimboTexto estado="neutro">Confere</CarimboTexto>
        </Link>
        <p className="selo-modo topo__selo">
          <strong>Modo demonstração:</strong> análise por regras, sem IA.
        </p>
      </header>

      <main className="folha" id="folha" tabIndex={-1}>
        <p className="selo-modo selo-celular">
          <strong>Modo demonstração:</strong> análise por regras, sem IA.
        </p>
        {children}
      </main>
    </div>
  );
}

/** Estados comuns dentro da folha. */
export function Carregando({ texto = "Carregando…" }: { texto?: string }) {
  return (
    <p className="estado estado--carregando" role="status">
      {texto}
    </p>
  );
}

export function Erro({ erro, tentar }: { erro: unknown; tentar?: () => void }) {
  const mensagem = erro instanceof Error ? erro.message : "Algo deu errado.";
  return (
    <div className="estado estado--erro" role="alert">
      <p>{mensagem}</p>
      {tentar && (
        <button type="button" className="botao botao--secundario" onClick={tentar}>
          Tentar de novo
        </button>
      )}
    </div>
  );
}
