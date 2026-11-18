/** Rótulos e formatação comuns às telas (pt-BR). */

export type Estado = "atende" | "parcial" | "nao_atende";

export const PALAVRA_DO_CARIMBO: Record<Estado, string> = {
  atende: "Confere",
  parcial: "Em parte",
  nao_atende: "Não consta",
};

export const ROTULO_DO_ESTADO: Record<Estado, string> = {
  atende: "Atende",
  parcial: "Parcial",
  nao_atende: "Não atende",
};

export const ROTULO_DO_TIPO = { obrigatorio: "Obrigatório", desejavel: "Desejável" } as const;

/** "1/2" → "0,5"; "1" → "1,0"; "0" → "0". */
export function valorDoRequisito(valor: string): string {
  const [a = Number.NaN, b] = valor.split("/").map(Number);
  const n = b ? a / b : a;
  if (Number.isNaN(n)) return valor;
  return n === 0 ? "0" : n.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

/** Ângulo fixo por item (−2° a −4°), nunca sorteado a cada renderização. */
export function anguloDe(chave: string): number {
  let h = 0;
  for (const c of chave) h = (h * 31 + c.charCodeAt(0)) | 0;
  return -2 - (Math.abs(h) % 21) / 10;
}

const DATA = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" });
const DATA_CURTA = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit" });
const HORA = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });

export const data = (iso: string) => DATA.format(new Date(iso));
export const dataCurta = (iso: string) => DATA_CURTA.format(new Date(iso));
export const dataHora = (iso: string) => `${DATA.format(new Date(iso))}, ${HORA.format(new Date(iso))}`;

export const ETAPAS = [
  { id: "leitura", nome: "Leitura", texto: "Lê o arquivo e separa o texto visível do oculto." },
  { id: "anonimizacao", nome: "Anonimização", texto: "Tira nome, contatos, CPF, idade e endereço antes de qualquer leitura." },
  { id: "extracao", nome: "Extração", texto: "Lista competências, experiências e requisitos, cada um com o trecho de onde saiu." },
  { id: "ancoragem", nome: "Conferência do trecho", texto: "Confere se cada trecho está mesmo no texto. O que não está é descartado." },
  { id: "correspondencia", nome: "Correspondência", texto: "Liga cada requisito da vaga a uma evidência do currículo, ou à falta dela." },
  { id: "nota", nome: "Nota", texto: "Faz a conta: obrigatórios 70 %, desejáveis 20 %, senioridade 10 %." },
  { id: "feedback", nome: "Feedback", texto: "Escreve as lacunas e o que aprender, sem inventar competência." },
] as const;

export type EtapaId = (typeof ETAPAS)[number]["id"];

export const NOME_DO_DADO: Record<string, string> = {
  nome: "nome",
  email: "e-mail",
  telefone: "telefone",
  cpf: "CPF",
  nascimento: "data de nascimento",
  idade: "idade",
  endereco: "endereço",
  genero: "gênero",
  estado_civil: "estado civil",
  familia: "família",
  nacionalidade: "nacionalidade",
  foto: "foto",
  link: "link pessoal",
  rg: "RG",
};

export const ORIGEM = { pdf: "PDF", docx: "DOCX", texto: "texto colado" } as const;

/** Avisos da análise em frases que dizem o que aconteceu e o que foi feito. */
export function fraseDoAviso(tipo: string, motivo?: string | null): { titulo: string; feito: string } {
  switch (tipo) {
    case "texto_oculto":
      return {
        titulo: "Encontramos texto escondido no arquivo",
        feito: `${motivo ? `Motivo: ${motivo}. ` : ""}Esse texto não entrou na análise nem na nota.`,
      };
    case "instrucao_para_ia":
    case "injecao":
      return {
        titulo: "O currículo tem uma frase que tenta dar ordens ao sistema",
        feito: "A frase foi sinalizada e ignorada; a nota foi calculada sem ela.",
      };
    case "pdf_sem_texto":
      return { titulo: "O PDF não tem texto selecionável", feito: "Envie a versão exportada do editor, ou cole o texto." };
    case "vaga_sem_requisitos":
      return {
        titulo: "A vaga não tem requisitos reconhecíveis",
        feito: "Cole a descrição completa, com a lista de requisitos.",
      };
    case "calculo":
      // O mesmo tipo cobre o modelo de embeddings ausente e os pesos redistribuídos (nota.py).
      if (!motivo || motivo.includes("embeddings")) {
        return {
          titulo: "Sem o modelo de similaridade",
          feito: "A correspondência usou só a taxonomia; termos fora dela ficaram sem similaridade.",
        };
      }
      return {
        titulo: "A conta foi ajustada a esta vaga",
        feito: `${motivo.charAt(0).toUpperCase()}${motivo.slice(1)}.`,
      };
    case "sem_texto":
      return { titulo: "Não encontramos texto no arquivo", feito: "Envie outro arquivo ou cole o texto." };
    case "nome_nao_identificado":
      return {
        titulo: "Não reconhecemos o nome no cabeçalho",
        feito: "Contatos e documentos foram removidos; confira a lista do que saiu.",
      };
    case "formulario_nao_lido":
    case "comentario_nao_lido":
      return {
        titulo: tipo === "formulario_nao_lido" ? "O arquivo tem campos de formulário" : "O arquivo tem comentários",
        feito: "Eles não foram lidos e não entraram na análise.",
      };
    default:
      return { titulo: tipo.replaceAll("_", " "), feito: motivo ?? "" };
  }
}
