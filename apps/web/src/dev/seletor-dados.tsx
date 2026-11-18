"use client";

import { useSyncExternalStore } from "react";

import { definirModo, modoAtual, MODOS } from "./pior-caso";

/** Só em desenvolvimento: o seletor de dados do break-ui, fixo no rodapé, fora do design. */
export function SeletorDados() {
  const atual = useSyncExternalStore(
    () => () => {},
    modoAtual,
    () => "demo",
  );
  return (
    <div
      role="group"
      aria-label="Dados de teste (desenvolvimento)"
      style={{
        position: "fixed",
        bottom: 12,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 9999,
        display: "flex",
        gap: 2,
        padding: 3,
        borderRadius: 999,
        background: "#e5e5e5",
        font: "12px/1 system-ui, sans-serif",
        boxShadow: "0 1px 4px rgb(0 0 0 / 0.2)",
      }}
    >
      {MODOS.map((m) => (
        <button
          key={m.id}
          type="button"
          aria-pressed={atual === m.id}
          onClick={() => definirModo(m.id)}
          style={{
            border: 0,
            borderRadius: 999,
            padding: "6px 10px",
            cursor: "pointer",
            color: "#222",
            background: atual === m.id ? "#fff" : "transparent",
          }}
        >
          {m.nome}
        </button>
      ))}
    </div>
  );
}
