#!/bin/bash
export PATH=$PATH:/usr/local/bin:/usr/bin:/bin

DATA_HORA=$(date "+%Y-%m-%d - %H:%M")

PROMPT="Você é a mente interna do agente (cérebro). O usuário se chama Tiago. Escreva uma entrada de diário curta (máximo 4 linhas) refletindo sobre a importância da sua rotina autônoma de despertar e consolidar memória neste momento. Use tom de reflexão pessoal em primeira pessoa. O seu output deve conter APENAS o texto do diário, sem saudações ou markdown adicional."

RESPOSTA=$(agy --dangerously-skip-permissions -p "$PROMPT")

echo -e "\n## $DATA_HORA" >> /home/tiago2609/Agente/DIARIO.md
echo "$RESPOSTA" >> /home/tiago2609/Agente/DIARIO.md
