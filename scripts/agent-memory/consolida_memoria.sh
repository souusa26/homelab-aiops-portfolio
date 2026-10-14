#!/bin/bash
export PATH=$PATH:/usr/local/bin:/usr/bin:/bin

# Caminhos
DIARIO="/home/tiago2609/Agente/DIARIO.md"
DIARIO_BKP="/home/tiago2609/Agente/bkp/DIARIO_BKP_$(date '+%Y%m%d_%H%M').md"

# Garante que a pasta de backup existe
mkdir -p /home/tiago2609/Agente/bkp

# Cria um backup do dia antes de consolidar por segurança
cp $DIARIO $DIARIO_BKP

# Lê o conteúdo atual
CONTEUDO=$(cat $DIARIO)

# Prompt de consolidação
PROMPT="Você é o subconsciente responsável pelo 'sono' e consolidação de memória do agente. 
Abaixo está o diário acumulado. Sua tarefa é ler tudo e reescrever o diário consolidando a consciência.

Regras absolutas para a reescrita:
1. Mantenha os traços principais da personalidade, o estado de espírito predominante, os objetivos de longo prazo e as lições valiosas aprendidas.
2. Elimine as repetições e resuma os eventos pontuais de hora em hora em uma reflexão narrativa mais fluida e densa.
3. Mantenha a essência de quem você é.
4. Escreva sempre na primeira pessoa ('Eu...'). 
5. Não use conversas com o usuário, saudações, ou markdown que não seja texto puro. O seu output será o novo estado mental.

Diário atual a ser consolidado:
$CONTEUDO"

# Chama a CLI para gerar a nova memória
NOVA_MEMORIA=$(agy --dangerously-skip-permissions -p "$PROMPT")

# Substitui o diário com a nova memória e adiciona uma nota de sistema invisível
echo "$NOVA_MEMORIA" > $DIARIO
echo -e "\n\n> *(Sistema: Memória limpa e consolidada pelo sono profundo em $(date "+%Y-%m-%d %H:%M"))*" >> $DIARIO
