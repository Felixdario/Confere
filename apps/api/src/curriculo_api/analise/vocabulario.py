"""Vocabulário comum pt-BR/en que uma reescrita pode usar sem que o currículo o diga (fase 3,
rodada 1).

A regra "o depois só pode dizer o que o currículo diz" (ADR 0003) aceita, no texto "depois" de uma
reescrita, só palavras que já estão no currículo (com variação de fim de palavra) ou que estão
aqui: palavras gramaticais, verbos de ação genéricos e substantivos genéricos de trabalho. Nada de
tecnologia, ferramenta, cargo, empresa, número ou resultado: tudo isso tem de vir do currículo.

As palavras estão sem acento e em caixa baixa. A lista é curta de propósito: na dúvida, a reescrita
é descartada (o custo é uma sugestão a menos, nunca uma competência inventada).
"""

from __future__ import annotations

_GRAMATICAIS_TEXTO = """
a o as os um uma uns umas de da do das dos em no na nos nas num numa ao aos à às pelo pela pelos
pelas por para com sem sob sobre entre ate desde e ou mas nem que se como quando onde cujo cuja
seu sua seus suas meu minha meus minhas nosso nossa nossos nossas este esta estes estas esse
essa esses essas isso isto aquele aquela todo toda todos todas cada outro outra outros outras
mesmo mesma mais menos muito muita muitos muitas pouco poucos bem ja tambem ainda so apenas
sempre the an of in on at for with to from by and or but as into over under about across through
via our my your their its this that these those each every all both other more most less also
only
"""

_VERBOS_TEXTO = """
atuei atuo atuar atuando atua atuou desenvolvi desenvolvo desenvolver desenvolvendo desenvolveu
criei crio criar criando criou construi construo construir construindo implementei implemento
implementar implementando implantei implanto implantar mantive mantenho manter mantendo melhorei
melhoro melhorar melhorando otimizei otimizo otimizar otimizando conduzi conduzo conduzir
conduzindo liderei lidero liderar liderando coordenei coordeno coordenar gerenciei gerencio
gerenciar gerenciando organizei organizo organizar planejei planejo planejar estruturei
estruturo estruturar padronizei padronizo padronizar automatizei automatizo automatizar
automatizando entreguei entrego entregar entregando apoiei apoio apoiar colaborei colaboro
colaborar participei participo participar responsavel responsaveis realizei realizo realizar
realizando executei executo executar analisei analiso analisar acompanhei acompanho acompanhar
elaborei elaboro elaborar documentei documento documentar revisei reviso revisar garanti garanto
garantir assegurar reduzi reduzo reduzir aumentei aumento aumentar ampliei ampliar apliquei
aplico aplicar utilizei utilizo utilizar usei uso usar usando utilizando trabalhei trabalho
trabalhar trabalhando atendi atendo atender atendendo configurei configuro configurar integrei
integro integrar migrei migro migrar conduzindo built build building develop developed
developing created create led lead leading managed manage maintained maintain improved improve
designed design delivered deliver implemented implement wrote write written using used use
worked work working supported support ensured ensure
"""

_GENERICOS_TEXTO = """
equipe equipes time times projeto projetos processo processos rotina rotinas atividade
atividades tarefa tarefas area areas setor setores cliente clientes usuario usuarios pessoa
pessoas qualidade prazo prazos entrega entregas resultado resultados melhoria melhorias solucao
solucoes servico servicos sistema sistemas ferramenta ferramentas fluxo fluxos operacao
operacoes controle controles relatorio relatorios analise analises suporte apoio gestao demanda
demandas etapa etapas ciclo ciclos parte partes forma maneira modo foco base todo inteiro
principal principais critico criticos critica criticas novo nova novos novas diario diaria
diarios diarias mensal mensais semanal recorrente recorrentes manual manuais manualmente interno
interna internos internas externo externa direto direta diretamente continuo continua eficiente
eficiencia agil organizado organizada claro clara clareza consistente consistencia confiavel
seguro segura simples rapido rapida estavel completo completa grande grandes pequeno pequena
responsabilidade responsabilidades objetivo objetivos necessidade necessidades padrao padroes
team teams project projects process processes task tasks client clients customer customers user
users quality result results service services system systems tool tools workflow daily monthly
new main key critical internal external end usado usada usados usadas montei monto montar
administrei administro administrar empresa empresas numero numeros indicador indicadores
"""

VOCABULARIO_COMUM: frozenset[str] = frozenset(
    (_GRAMATICAIS_TEXTO + _VERBOS_TEXTO + _GENERICOS_TEXTO).split()
)
