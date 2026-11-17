import clsx from "clsx";
import type { CSSProperties } from "react";

import { anguloDe, PALAVRA_DO_CARIMBO, ROTULO_DO_ESTADO, valorDoRequisito, type Estado } from "@/lib/textos";

/**
 * O carimbo de estado: um `<span>` com o texto real e o rótulo acessível completo
 * ("Atende: 1,0"). Em linhas de tabela fica reto; grande, inclina num ângulo fixo por item.
 */
export function Carimbo({
  estado,
  valor,
  grande = false,
  inclinar,
  cai = false,
  chave,
  className,
}: {
  estado: Estado;
  valor?: string;
  grande?: boolean;
  /** Ângulo em graus; por padrão, só o carimbo grande inclina (derivado de `chave`). */
  inclinar?: number;
  cai?: boolean;
  chave?: string;
  className?: string;
}) {
  const angulo = inclinar ?? (grande ? anguloDe(chave ?? estado) : 0);
  const rotulo = `${ROTULO_DO_ESTADO[estado]}${valor !== undefined ? `: ${valorDoRequisito(valor)}` : ""}`;
  return (
    <span
      className={clsx("carimbo", grande && "carimbo--grande", cai && "carimbo--cai", className)}
      data-estado={estado}
      style={{ "--angulo": `${angulo}deg` } as CSSProperties}
      role="img"
      aria-label={rotulo}
    >
      {PALAVRA_DO_CARIMBO[estado]}
    </span>
  );
}

/** Carimbo de texto livre (marca, "não medido", etapas). */
export function CarimboTexto({
  children,
  estado = "atende",
  grande = false,
  inclinar = 0,
  cai = false,
  className,
}: {
  children: string;
  estado?: Estado | "neutro";
  grande?: boolean;
  inclinar?: number;
  cai?: boolean;
  className?: string;
}) {
  return (
    <span
      className={clsx("carimbo", grande && "carimbo--grande", cai && "carimbo--cai", className)}
      data-estado={estado}
      style={{ "--angulo": `${inclinar}deg` } as CSSProperties}
    >
      {children}
    </span>
  );
}
