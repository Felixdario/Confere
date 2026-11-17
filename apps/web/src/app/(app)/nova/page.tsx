"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { FormNovaAnalise } from "@/componentes/form-nova-analise";

function Nova() {
  const busca = useSearchParams();
  const curriculoId = busca.get("curriculo") ?? undefined;
  const vagaId = busca.get("vaga");
  const vagaTitulo = busca.get("titulo");
  const vaga = vagaId && vagaTitulo ? { id: vagaId, titulo: vagaTitulo } : undefined;
  return (
    <>
      <title>Nova análise · Confere</title>
      <div className="cabeca-tela">
        <div>
          <h1 className="titulo-tela">{curriculoId ? "Nova versão do currículo" : "Nova análise"}</h1>
          <p className="subtitulo-tela">
            {curriculoId
              ? "Envie a versão ajustada. Ela entra no histórico ao lado da anterior, para comparar requisito por requisito."
              : "O currículo e a vaga. Você acompanha cada etapa enquanto a análise roda."}
          </p>
        </div>
      </div>
      <div className="nova-tela">
        <FormNovaAnalise curriculoId={curriculoId} vaga={vaga} />
      </div>
    </>
  );
}

export default function PaginaNova() {
  return (
    <Suspense>
      <Nova />
    </Suspense>
  );
}
