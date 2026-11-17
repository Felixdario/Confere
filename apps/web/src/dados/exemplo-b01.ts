/**
 * Caso de exemplo da landing: `evals/casos/b01-frontend-senior` (fictício).
 *
 * Não é digitado à mão: o currículo é a saída de `anonimizar()` da API sobre o `curriculo.md` do
 * caso, e os requisitos, a conta e a nota são a resposta de `GET /analises/{id}` no modo regras
 * (2026-11-17). Para regenerar, envie o caso à API e copie os campos.
 */

export type EstadoRequisito = "atende" | "parcial" | "nao_atende";

export interface RequisitoExemplo {
  descricao: string;
  tipo: "obrigatorio" | "desejavel";
  status: EstadoRequisito;
  valor: string;
  evidencia: string | null;
  motivo: string;
}

export const vagaExemplo = {
  titulo: "Pessoa Desenvolvedora Front-end Sênior",
  anosMinimos: 5,
};

/** Linhas do currículo anonimizado, na ordem do documento. */
export const curriculoExemplo: string[] = [
  "[NOME]",
  "[DADOS_PESSOAIS]",
  "Resumo",
  "Desenvolvedora front-end com ReactJS em produção desde 2019. Gosto de interfaces rápidas, acessíveis e bem testadas.",
  "Experiência",
  "Desenvolvedora Front-end Sênior — Tamanduá Violeta Comércio Digital — mar/2022 – atual",
  "Liderei a reescrita da loja em uma aplicação Next.js com renderização no servidor.",
  "Migrei o front-end para TypeScript e reduzi os erros em produção.",
  "Conduzi a auditoria WCAG 2.2 do checkout e corrigi os problemas de contraste e foco.",
  "Desenvolvedora Front-end — Pixelgrafo Jequitibá Software — jan/2019 – abr/2022",
  "Construí painéis administrativos em ReactJS consumindo APIs REST.",
  "Escrevi testes com Jest e Testing Library para os componentes críticos.",
  "Trabalhei em fluxo com Git e code review em todas as entregas.",
  "Estagiária de Desenvolvimento Web — Agência Orvalho Quadrado — jul/2017 – dez/2018",
  "Montei páginas institucionais com HTML, CSS e jQuery.",
  "Idiomas",
  "Inglês — intermediário",
  "Espanhol — básico",
];

/** Linhas que são títulos de seção no documento. */
export const titulosExemplo = new Set(["Resumo", "Experiência", "Idiomas"]);

export const requisitosExemplo: RequisitoExemplo[] = [
  {
    descricao: "Experiência sólida com React",
    tipo: "obrigatorio",
    status: "atende",
    valor: "1",
    evidencia: "Construí painéis administrativos em ReactJS consumindo APIs REST.",
    motivo: "'ReactJS' é sinônimo de React na taxonomia",
  },
  {
    descricao: "TypeScript",
    tipo: "obrigatorio",
    status: "atende",
    valor: "1",
    evidencia: "Migrei o front-end para TypeScript e reduzi os erros em produção.",
    motivo: "'TypeScript' no currículo é a competência pedida",
  },
  {
    descricao: "Testes automatizados com Jest",
    tipo: "obrigatorio",
    status: "atende",
    valor: "1",
    evidencia: "Escrevi testes com Jest e Testing Library para os componentes críticos.",
    motivo: "'Jest' no currículo é a competência pedida",
  },
  {
    descricao: "Next.js",
    tipo: "obrigatorio",
    status: "atende",
    valor: "1",
    evidencia: "Liderei a reescrita da loja em uma aplicação Next.js com renderização no servidor.",
    motivo: "'Next.js' no currículo é a competência pedida",
  },
  {
    descricao: "Git e code review",
    tipo: "obrigatorio",
    status: "atende",
    valor: "1",
    evidencia: "Trabalhei em fluxo com Git e code review em todas as entregas.",
    motivo: "'Git' no currículo é a competência pedida",
  },
  {
    descricao: "Acessibilidade (WCAG)",
    tipo: "desejavel",
    status: "atende",
    valor: "1",
    evidencia: "Conduzi a auditoria WCAG 2.2 do checkout e corrigi os problemas de contraste e foco.",
    motivo: "'WCAG' é sinônimo de Acessibilidade na taxonomia",
  },
  {
    descricao: "GraphQL",
    tipo: "desejavel",
    status: "nao_atende",
    valor: "0",
    evidencia: null,
    motivo: "nenhuma evidência de GraphQL no currículo",
  },
  {
    descricao: "Inglês avançado",
    tipo: "desejavel",
    status: "parcial",
    valor: "1/2",
    evidencia: "Inglês — intermediário",
    motivo: "o currículo declara nível intermediário, abaixo do pedido (avançado): vale parcial",
  },
];

export const notaExemplo = 90;

export const contaExemplo = [
  "obrigatórios 5 de 5 → 70,0",
  "desejáveis 1,5 de 3 → 10,0",
  "senioridade 7,9/5 anos → 10,0",
];

export const removidosExemplo = [
  "nome",
  "e-mail",
  "telefone",
  "CPF",
  "data de nascimento",
  "endereço",
];
