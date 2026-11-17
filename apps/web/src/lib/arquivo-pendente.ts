/**
 * O rascunho da nova análise (arquivo, texto colado, vaga) segue da landing para a tela de nova
 * análise, e de lá para o login e de volta, sem passar pela URL nem pelo armazenamento do
 * navegador: fica só na memória desta aba.
 */
export interface Rascunho {
  arquivo: File | null;
  texto: string;
  vaga: string;
}

let pendente: Rascunho | null = null;

export function guardarRascunho(r: Partial<Rascunho>) {
  pendente = { arquivo: null, texto: "", vaga: "", ...pendente, ...r };
}

export function retirarRascunho(): Rascunho | null {
  const r = pendente;
  pendente = null;
  return r;
}

export const TIPOS_ACEITOS =
  ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";
export const TAMANHO_MAX = 5 * 1024 * 1024;

/** Confere tipo e tamanho antes de enviar; devolve a mensagem de erro ou null. */
export function problemaDoArquivo(arquivo: File): string | null {
  const nome = arquivo.name.toLowerCase();
  if (!nome.endsWith(".pdf") && !nome.endsWith(".docx")) {
    return "Envie um PDF ou um DOCX. Outro formato: cole o texto.";
  }
  if (arquivo.size > TAMANHO_MAX) return "O arquivo passa de 5 MB. Exporte uma versão menor ou cole o texto.";
  if (arquivo.size === 0) return "O arquivo está vazio.";
  return null;
}

export function tamanhoLegivel(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} MB`;
}
