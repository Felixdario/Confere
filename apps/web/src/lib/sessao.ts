"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { api, ErroApi, esquecerCsrf, type Eu } from "./api";

/** A pessoa da sessão, ou null sem sessão (401). Outros erros sobem para a tela. */
export function useEu() {
  return useQuery({
    queryKey: ["eu"],
    queryFn: async () => {
      try {
        return await api<Eu>("/eu");
      } catch (e) {
        if (e instanceof ErroApi && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
  });
}

/** Telas que pedem conta: sem sessão, vão para o login e voltam depois. */
export function useExigirSessao() {
  const eu = useEu();
  const router = useRouter();
  const caminho = usePathname();
  useEffect(() => {
    if (eu.data === null) router.replace(`/entrar?volta=${encodeURIComponent(caminho)}`);
  }, [eu.data, router, caminho]);
  return eu;
}

export function useSair() {
  const cliente = useQueryClient();
  const router = useRouter();
  return async () => {
    await api("/auth/logout", { metodo: "POST" }).catch(() => undefined);
    esquecerCsrf();
    cliente.clear();
    router.push("/");
  };
}
