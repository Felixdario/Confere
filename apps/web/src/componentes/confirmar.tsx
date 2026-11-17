"use client";

import { AlertDialog } from "@base-ui/react/alert-dialog";
import clsx from "clsx";
import { useState, type ReactNode } from "react";

import "./confirmar.css";

/** Confirmação de ação séria (base-ui AlertDialog: foco preso, Esc fecha, volta o foco ao botão). */
export function Confirmar({
  gatilho,
  titulo,
  children,
  confirmar,
  aoConfirmar,
  perigo = false,
  classeGatilho,
}: {
  gatilho: string;
  titulo: string;
  children: ReactNode;
  confirmar: string;
  aoConfirmar: () => Promise<void> | void;
  perigo?: boolean;
  classeGatilho?: string;
}) {
  const [aberto, setAberto] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  return (
    <AlertDialog.Root open={aberto} onOpenChange={setAberto}>
      <AlertDialog.Trigger className={clsx("botao", perigo ? "botao--perigo" : "botao--secundario", classeGatilho)}>
        {gatilho}
      </AlertDialog.Trigger>
      <AlertDialog.Portal>
        <AlertDialog.Backdrop className="dialogo__fundo" />
        <AlertDialog.Popup className="dialogo">
          <AlertDialog.Title className="dialogo__titulo">{titulo}</AlertDialog.Title>
          <AlertDialog.Description render={<div />} className="dialogo__texto">
            {children}
          </AlertDialog.Description>
          <div className="dialogo__acoes">
            <AlertDialog.Close className="botao botao--secundario">Cancelar</AlertDialog.Close>
            <button
              type="button"
              className={clsx("botao", perigo && "botao--perigo")}
              disabled={ocupado}
              onClick={async () => {
                setOcupado(true);
                try {
                  await aoConfirmar();
                  setAberto(false);
                } finally {
                  setOcupado(false);
                }
              }}
            >
              {ocupado ? "Aguarde…" : confirmar}
            </button>
          </div>
        </AlertDialog.Popup>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
