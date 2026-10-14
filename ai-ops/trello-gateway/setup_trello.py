import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("TRELLO_API_KEY")
TOKEN = os.getenv("TRELLO_TOKEN")

base_url = "https://api.trello.com/1"
auth = {"key": API_KEY, "token": TOKEN}

# 1. Localize o quadro chamado "Mudança CANADA"
response = requests.get(f"{base_url}/members/me/boards", params=auth)
boards = response.json()
board = next((b for b in boards if b["name"] == "Mudança CANADA"), None)

if not board:
    print("Quadro não encontrado!")
    exit(1)

board_id = board["id"]
print(f"Quadro encontrado: {board['name']} (ID: {board_id})")

# 2. Crie as listas (colunas) da esquerda para a direita
list_names = [
    "Wiki & Referências",
    "Backlog (Longo Prazo)",
    "To Do (Curto Prazo)",
    "Em Andamento",
    "Aguardando Terceiros",
    "Concluído"
]

created_lists = {}
# Para criar da esquerda pra direita, a posição 'bottom' garante que a nova lista vá para a direita da última
for name in list_names:
    res = requests.post(
        f"{base_url}/lists", 
        params={**auth, "name": name, "idBoard": board_id, "pos": "bottom"}
    )
    res_data = res.json()
    created_lists[name] = res_data["id"]
    print(f"Lista criada: {name} (ID: {res_data['id']})")

# 3. Crie os cartões dentro da lista "To Do (Curto Prazo)"
todo_list_id = created_lists["To Do (Curto Prazo)"]
todo_cards = [
    {
        "name": "Alinhamento com a prima",
        "desc": "Conversar, pegar dicas de empresas locais (especialmente no polo logístico, automotivo e industrial da região de Essex) e verificar a possibilidade de indicações."
    },
    {
        "name": "Pesquisa de Custo de Vida em Windsor",
        "desc": "Usar sites como Kijiji e Realtor.ca para mapear o custo médio de aluguel na cidade e despesas de rotina."
    },
    {
        "name": "Revisar CVs e LinkedIn para o padrão Canadense",
        "desc": "Ajustar os currículos removendo foto, idade e estado civil. Focar em resultados. Destacar a certificação de TI."
    },
    {
        "name": "Definir meta financeira e iniciar compra de CAD",
        "desc": "Estimar custos (vistos, passagens, 3 meses de aluguel/caução baseados no custo de Windsor, tradução de documentos) e definir o valor de aporte mensal."
    }
]

for card in todo_cards:
    res = requests.post(
        f"{base_url}/cards",
        params={**auth, "idList": todo_list_id, "name": card["name"], "desc": card["desc"], "pos": "bottom"}
    )
    print(f"Cartão criado em 'To Do (Curto Prazo)': {card['name']}")

# 4. Crie os cartões dentro da lista "Backlog (Longo Prazo)"
backlog_list_id = created_lists["Backlog (Longo Prazo)"]
backlog_cards = [
    {
        "name": "Pesquisar regras e checklist do Spousal Open Work Permit (SOWP)",
        "desc": "Levantar a documentação necessária (incluindo comprovação de união estável) para aplicar para o visto aberto de cônjuge atrelado à futura vaga de TI."
    },
    {
        "name": "Busca de vagas e Sponsor (Ontário/Windsor)",
        "desc": "Mapear empresas em Windsor, pesquisar a WEtech Alliance e buscar vagas remotas em Ontário que ofereçam LMIA/Visa Sponsorship. Fazer networking e agendar Coffee Chats."
    },
    {
        "name": "Busca de vagas (Plano B e Sobrevivência)",
        "desc": "Pesquisar vagas em centros de distribuição e logística na fronteira, e mapear oportunidades técnicas de manutenção de sistemas e infraestrutura industrial local."
    },
    {
        "name": "Comprovação de Idioma (IELTS/CELPIP)",
        "desc": "Agendar e realizar o teste de proficiência. (Prioridade: Ana)."
    },
    {
        "name": "Tradução Juramentada e Exames Médicos",
        "desc": "Separar diplomas, certidões de antecedentes criminais e agendar exames médicos credenciados pelo IRCC (apenas após a oferta)."
    }
]

for card in backlog_cards:
    res = requests.post(
        f"{base_url}/cards",
        params={**auth, "idList": backlog_list_id, "name": card["name"], "desc": card["desc"], "pos": "bottom"}
    )
    print(f"Cartão criado em 'Backlog (Longo Prazo)': {card['name']}")

print("Execução concluída com sucesso.")
