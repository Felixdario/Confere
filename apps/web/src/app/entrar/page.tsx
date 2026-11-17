"use client";

import { Tabs } from "@base-ui/react/tabs";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { CarimboTexto } from "@/componentes/carimbo";
import { api, esquecerCsrf, type Privacidade } from "@/lib/api";

import "../(app)/app.css";
import "./entrar.css";

/** Só caminhos internos: nada de redirecionar para outro site pelo `?volta=`. */
function destinoSeguro(volta: string | null) {
  return volta && volta.startsWith("/") && !volta.startsWith("//") ? volta : "/historico";
}

function Entrar() {
  const router = useRouter();
  const busca = useSearchParams();
  const volta = destinoSeguro(busca.get("volta"));
  const cliente = useQueryClient();
  const priv = useQuery({ queryKey: ["privacidade"], queryFn: () => api<Privacidade>("/privacidade") });

  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [aceito, setAceito] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function concluir(acao: () => Promise<unknown>) {
    setErro(null);
    setEnviando(true);
    try {
      await acao();
      esquecerCsrf();
      await cliente.invalidateQueries({ queryKey: ["eu"] });
      router.push(volta);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível entrar.");
      setEnviando(false);
    }
  }

  const entrar = (e: FormEvent) => {
    e.preventDefault();
    void concluir(() => api("/auth/login", { metodo: "POST", corpo: { email, senha } }));
  };

  const cadastrar = (e: FormEvent) => {
    e.preventDefault();
    if (!aceito) {
      setErro("Para criar a conta, aceite o tratamento dos dados descrito acima.");
      return;
    }
    void concluir(() =>
      api("/auth/cadastro", {
        metodo: "POST",
        corpo: { email, senha, aceito_consentimento: true, versao_consentimento: priv.data?.versao_texto ?? "" },
      }),
    );
  };

  const demonstracao = () =>
    void concluir(() =>
      api("/auth/login", { metodo: "POST", corpo: { email: "demo@curriculo.dev", senha: "demo1234" } }),
    );

  return (
    <div className="entrar">
      <title>Entrar · Confere</title>
      <Link href="/" className="entrar__marca" aria-label="Confere, página inicial">
        <CarimboTexto estado="neutro">Confere</CarimboTexto>
      </Link>
      <main className="entrar__folha">
        <h1 className="titulo-tela">Entrar no Confere</h1>
        <p className="subtitulo-tela">
          A conta guarda suas análises para você comparar versões do currículo.
        </p>

        <div className="entrar__demo">
          <p>
            Só quer ver como funciona? A conta de demonstração já tem análises prontas, uma triagem de
            recrutador e versões para comparar.
          </p>
          <button type="button" className="botao" onClick={demonstracao} disabled={enviando}>
            Entrar na demonstração
          </button>
        </div>

        <Tabs.Root defaultValue="entrar" className="entrar__abas" onValueChange={() => setErro(null)}>
          <Tabs.List className="abas" aria-label="Entrar ou criar conta">
            <Tabs.Tab value="entrar" className="abas__aba">
              Entrar
            </Tabs.Tab>
            <Tabs.Tab value="criar" className="abas__aba">
              Criar conta
            </Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="entrar">
            <form className="entrar__form" onSubmit={entrar}>
              <div className="campo">
                <label htmlFor="email-entrar">E-mail</label>
                <input
                  id="email-entrar"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.currentTarget.value)}
                />
              </div>
              <div className="campo">
                <label htmlFor="senha-entrar">Senha</label>
                <input
                  id="senha-entrar"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={senha}
                  onChange={(e) => setSenha(e.currentTarget.value)}
                />
              </div>
              {erro && (
                <p className="entrar__erro" role="alert">
                  {erro}
                </p>
              )}
              <button type="submit" className="botao" disabled={enviando}>
                {enviando ? "Entrando…" : "Entrar"}
              </button>
            </form>
          </Tabs.Panel>

          <Tabs.Panel value="criar">
            <form className="entrar__form" onSubmit={cadastrar}>
              <div className="campo">
                <label htmlFor="email-criar">E-mail</label>
                <input
                  id="email-criar"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.currentTarget.value)}
                />
              </div>
              <div className="campo">
                <label htmlFor="senha-criar">Senha</label>
                <input
                  id="senha-criar"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={8}
                  aria-describedby="senha-dica"
                  value={senha}
                  onChange={(e) => setSenha(e.currentTarget.value)}
                />
                <p id="senha-dica" className="campo__dica">
                  Pelo menos 8 caracteres.
                </p>
              </div>
              {priv.data && (
                <div className="entrar__consentimento">
                  <p>{priv.data.texto_consentimento}</p>
                  <label className="marcar">
                    <input type="checkbox" checked={aceito} onChange={(e) => setAceito(e.currentTarget.checked)} />
                    <span>
                      Li e aceito. Os dados ficam {priv.data.retencao_dias} dias e posso apagar tudo quando quiser.{" "}
                      <Link href="/privacidade">O que é guardado</Link>
                    </span>
                  </label>
                </div>
              )}
              {erro && (
                <p className="entrar__erro" role="alert">
                  {erro}
                </p>
              )}
              <button type="submit" className="botao" disabled={enviando || !priv.data}>
                {enviando ? "Criando…" : "Criar conta"}
              </button>
            </form>
          </Tabs.Panel>
        </Tabs.Root>
      </main>
    </div>
  );
}

export default function PaginaEntrar() {
  return (
    <Suspense>
      <Entrar />
    </Suspense>
  );
}
