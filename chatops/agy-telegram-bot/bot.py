#!/usr/bin/env python3
"""
Antigravity Telegram Bot
Permite interagir com o Google Antigravity CLI (agy) diretamente pelo Telegram.
"""

import os
import sys
import json
import re
import time
import signal
import logging
import subprocess
import threading
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv
import telebot
from telebot.types import BotCommand, InlineKeyboardMarkup, InlineKeyboardButton
from telebot.apihelper import ApiTelegramException

# Configuração de Logs
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("agy-bot")

# Carregar variáveis de ambiente
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_IDS_RAW = os.getenv("ALLOWED_CHAT_IDS", "")


def parse_chat_id(val: str) -> Optional[int]:
    val = val.strip()
    try:
        return int(val)
    except ValueError:
        return None


ALLOWED_CHAT_IDS = [
    cid for val in ALLOWED_CHAT_IDS_RAW.split(",") if (cid := parse_chat_id(val)) is not None
]

# Fail-fast: sem token ou sem allowlist o bot não sobe. Um agente com
# --dangerously-skip-permissions exposto a qualquer chat seria um shell aberto.
if not TOKEN or not ALLOWED_CHAT_IDS:
    logger.critical("TELEGRAM_BOT_TOKEN e ALLOWED_CHAT_IDS são obrigatórios (veja .env.example).")
    sys.exit(1)

AGY_PATH = os.getenv("AGY_PATH", "/usr/local/bin/agy")
DEFAULT_WORKSPACE = os.getenv("DEFAULT_WORKSPACE", os.path.expanduser("~"))
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemini-3.8-flash-high")
DEFAULT_EFFORT = os.getenv("DEFAULT_EFFORT", "high")
TIMEOUT_SECONDS = int(os.getenv("TIMEOUT_SECONDS", "600"))
SESSIONS_FILE = os.path.join(BASE_DIR, "sessions.json")

# Filtros regex
ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
LOCAL_URL_CLEANER = re.compile(r'\[([^\]]+)\]\((?:file|conversation)://[^\)]+\)')

# Estado em memória com RLock (Reentrant Lock para evitar deadlocks)
sessions_lock = threading.RLock()
sessions: Dict[str, Dict[str, Any]] = {}

active_tasks_lock = threading.RLock()
active_tasks: Dict[int, Dict[str, Any]] = {}


def load_sessions() -> None:
    """Carrega as sessões salvas do arquivo JSON."""
    global sessions
    with sessions_lock:
        if os.path.exists(SESSIONS_FILE):
            try:
                with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                    sessions = json.load(f)
                logger.info(f"Sessões carregadas: {len(sessions)} ativas.")
            except Exception as e:
                logger.error(f"Erro ao carregar sessions.json: {e}")
                sessions = {}
        else:
            sessions = {}


def save_sessions() -> None:
    """Salva o estado das sessões no arquivo JSON."""
    with sessions_lock:
        try:
            with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(sessions, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Erro ao salvar sessions.json: {e}")


def get_session(chat_id: int) -> Dict[str, Any]:
    """Recupera ou inicializa a sessão para um determinado chat_id."""
    cid_str = str(chat_id)
    with sessions_lock:
        if cid_str not in sessions:
            ws = DEFAULT_WORKSPACE if os.path.isdir(DEFAULT_WORKSPACE) else BASE_DIR
            sessions[cid_str] = {
                "conversation_id": None,
                "workspace": ws,
                "model": DEFAULT_MODEL,
                "effort": DEFAULT_EFFORT,
                "turn_count": 0,
                "created_at": time.time(),
                "last_active": time.time(),
            }
            save_sessions()
        return sessions[cid_str]


def update_session(chat_id: int, **kwargs) -> None:
    """Atualiza campos da sessão do chat_id."""
    cid_str = str(chat_id)
    with sessions_lock:
        if cid_str in sessions:
            sessions[cid_str].update(kwargs)
            sessions[cid_str]["last_active"] = time.time()
            save_sessions()


def is_authorized(chat_id: int) -> bool:
    """Verifica se o chat_id está autorizado."""
    return chat_id in ALLOWED_CHAT_IDS


def sanitize_text(text: str) -> str:
    """Remove códigos ANSI e corrige links file:// e conversation:// que quebram o parser do Telegram."""
    if not text:
        return ""
    cleaned = ANSI_ESCAPE.sub("", text)
    cleaned = LOCAL_URL_CLEANER.sub(r"`\1`", cleaned)
    return cleaned


def smart_split(text: str, max_length: int = 3800) -> List[str]:
    """Divide o texto em blocos de até max_length caracteres de forma inteligente."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text

    while len(remaining) > max_length:
        split_pos = remaining.rfind("\n\n", 0, max_length)
        if split_pos == -1 or split_pos < max_length // 2:
            split_pos = remaining.rfind("\n", 0, max_length)
        if split_pos == -1 or split_pos < max_length // 2:
            split_pos = remaining.rfind(" ", 0, max_length)
        if split_pos == -1:
            split_pos = max_length

        chunk = remaining[:split_pos].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_pos:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


def send_formatted_response(bot_instance: telebot.TeleBot, chat_id: int, text: str, footer: Optional[str] = None) -> None:
    """Envia texto em blocos respeitando o limite do Telegram e tratando erros de Markdown."""
    sanitized = sanitize_text(text)
    if footer:
        sanitized = f"{sanitized}\n\n{footer}"

    chunks = smart_split(sanitized)
    for chunk in chunks:
        if not chunk.strip():
            continue
        try:
            bot_instance.send_message(chat_id, chunk, parse_mode="Markdown")
        except ApiTelegramException as e:
            logger.warning(f"Falha ao enviar Markdown para chat {chat_id} (tentando texto puro): {e}")
            try:
                bot_instance.send_message(chat_id, chunk, parse_mode=None)
            except Exception as err:
                logger.error(f"Erro crítico ao enviar mensagem de texto para chat {chat_id}: {err}")


def typing_worker(bot_instance: telebot.TeleBot, chat_id: int, stop_event: threading.Event) -> None:
    """Mantém a ação 'typing' ativa no Telegram enquanto o Antigravity processa."""
    while not stop_event.is_set():
        try:
            bot_instance.send_chat_action(chat_id, "typing")
        except Exception:
            pass
        stop_event.wait(4.0)


def extract_agy_json(raw_output: str) -> Optional[Dict[str, Any]]:
    """Tenta extrair o JSON retornado pelo agy com suporte a logs/warnings prévios."""
    if not raw_output:
        return None
    raw = raw_output.strip()

    # Tentativa 1: Parse direto
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # Tentativa 2: Primeira '{' até a última '}'
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        try:
            data = json.loads(raw[first_brace:last_brace + 1])
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    # Tentativa 3: Linha por linha (NDJSON ou saída estruturada com warnings)
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                data = json.loads(line)
                if isinstance(data, dict) and ("conversation_id" in data or "response" in data or "status" in data or "command" in data):
                    return data
            except Exception:
                continue

    return None


# Inicialização do Bot
bot = telebot.TeleBot(TOKEN)
load_sessions()


# ==========================================
# COMANDOS DO BOT
# ==========================================

@bot.message_handler(commands=["start", "help"])
def cmd_help(message):
    chat_id = message.chat.id
    if not is_authorized(chat_id):
        logger.warning(f"Acesso negado em /help: chat_id={chat_id}, username={getattr(message.from_user, 'username', 'desconhecido')}")
        bot.reply_to(message, f"⚠️ Acesso não autorizado. Seu chat ID é `{chat_id}`.", parse_mode="Markdown")
        return

    logger.info(f"[Chat {chat_id}] Executou /help ou /start")
    help_text = (
        "🤖 *Antigravity Telegram Bot*\n\n"
        "Envie qualquer instrução, dúvida ou tarefa de desenvolvimento em linguagem natural para interagir com o agente Antigravity no seu servidor.\n\n"
        "⚙️ *Comandos Disponíveis:*\n"
        "• `/status` — Status da sessão atual (pasta, modelo, ID da conversa)\n"
        "• `/pwd` — Ver pasta de trabalho atual e arquivos\n"
        "• `/cd <caminho>` — Alterar o diretório de trabalho do agente\n"
        "• `/new` ou `/reset` — Iniciar uma nova conversa do zero\n"
        "• `/models` — Listar modelos de IA disponíveis\n"
        "• `/model <nome>` — Alterar o modelo da sessão\n"
        "• `/effort <low|med|high>` — Ajustar nível de raciocínio\n"
        "• `/skills` — Ver habilidades disponíveis no Antigravity\n"
        "• `/cancel` — Interromper a tarefa em andamento\n"
        "• `/help` — Exibir este menu de ajuda\n"
    )
    send_formatted_response(bot, chat_id, help_text)


@bot.message_handler(commands=["new", "reset", "clear"])
def cmd_new(message):
    chat_id = message.chat.id
    if not is_authorized(chat_id):
        logger.warning(f"Acesso negado em /new: chat_id={chat_id}")
        bot.reply_to(message, f"⚠️ Acesso não autorizado. Seu chat ID é `{chat_id}`.", parse_mode="Markdown")
        return

    logger.info(f"[Chat {chat_id}] Executou /new (reset de sessão)")
    session = get_session(chat_id)
    old_id = session.get("conversation_id")
    update_session(chat_id, conversation_id=None, turn_count=0, total_tokens=0)

    msg = "✨ *Sessão resetada com sucesso!*\nO histórico anterior foi arquivado. Sua próxima mensagem iniciará uma nova conversa."
    if old_id:
        msg += f"\n\n_ID anterior: `{old_id}`_"
    send_formatted_response(bot, chat_id, msg)


def make_progress_bar(fraction: float, length: int = 10) -> str:
    filled = int(fraction * length)
    return "█" * filled + "░" * (length - filled)

@bot.message_handler(commands=["usage", "quota"])
def cmd_usage(message):
    chat_id = message.chat.id
    if not is_authorized(chat_id):
        return

    logger.info(f"[Chat {chat_id}] Executou /usage")
    session = get_session(chat_id)
    
    status_msg = bot.reply_to(message, "⏳ _Consultando quota do Antigravity..._", parse_mode="Markdown")
    
    total_tokens = session.get("total_tokens", 0)
    turn_count = session.get("turn_count", 0)
    
    msg = ""
    
    try:
        res = subprocess.run([AGY_PATH, "-p", "/usage", "--output-format", "json"], capture_output=True, text=True, timeout=10)
        parsed_json = extract_agy_json(res.stdout)
        
        if parsed_json and "command" in parsed_json and parsed_json["command"].get("name") == "usage":
            data = parsed_json["command"].get("data", {})
            msg += "📊 *Quota do Antigravity:*\n\n"
            desc = data.get('description', '')
            if desc:
                msg += f"_{desc}_\n\n"
            
            for group in data.get("groups", []):
                msg += f"🔹 *{group.get('name', 'Grupo')}*\n"
                for bucket in group.get("buckets", []):
                    name = bucket.get("name", "")
                    fraction = bucket.get("remaining_fraction", 0.0)
                    pct = int(fraction * 100)
                    # Formatar data de forma mais amigável, se possível, mas manter o original é OK
                    reset_time = bucket.get("reset_time", "")
                    
                    bar = make_progress_bar(fraction, 10)
                    msg += f"  {name}:\n"
                    msg += f"  `[{bar}] {pct}%` (Reseta: `{reset_time}`)\n"
                msg += "\n"
    except Exception as e:
        logger.error(f"Erro ao obter quota do Antigravity: {e}")
        msg += f"⚠️ _Não foi possível obter a quota do Antigravity: {e}_\n\n"

    msg += f"📈 *Uso da Sessão Atual:*\n"
    msg += f"🪙 *Tokens:* `{total_tokens:,}`\n".replace(',', '.')
    msg += f"🔄 *Interações:* `{turn_count}`\n\n"
    
    try:
        mem = subprocess.check_output(['free', '-h']).decode('utf-8').strip()
        df = subprocess.check_output(['df', '-h', '/']).decode('utf-8').strip()
        uptime = subprocess.check_output(['uptime', '-p']).decode('utf-8').strip()
        msg += f"💻 *Uso do Sistema:*\n"
        msg += f"⏱️ *Uptime:* `{uptime}`\n"
        msg += f"🧠 *Memória:*\n```text\n{mem}\n```\n"
        msg += f"💾 *Disco (/):*\n```text\n{df}\n```\n"
    except Exception as e:
        msg += f"_Erro ao obter uso do sistema: {e}_\n"

    msg += "\n_Dica: Para reiniciar a contagem de tokens, use /new._"
        
    try:
        # Tentar editar a mensagem de status para evitar spam
        bot.edit_message_text(msg, chat_id=chat_id, message_id=status_msg.message_id, parse_mode="Markdown")
    except Exception:
        # Fallback caso a formatação falhe (ex: markdown quebrado na msg longa)
        send_formatted_response(bot, chat_id, msg)


@bot.message_handler(commands=["status"])
def cmd_status(message):
    chat_id = message.chat.id
    if not is_authorized(chat_id):
        logger.warning(f"Acesso negado em /status: chat_id={chat_id}")
        bot.reply_to(message, f"⚠️ Acesso não autorizado. Seu chat ID é `{chat_id}`.", parse_mode="Markdown")
        return

    logger.info(f"[Chat {chat_id}] Executou /status")
    session = get_session(chat_id)
    with active_tasks_lock:
        is_busy = chat_id in active_tasks

    conv_id = session.get("conversation_id") or "Nenhuma (iniciará na próxima mensagem)"
    workspace = session.get("workspace", DEFAULT_WORKSPACE)
    model = session.get("model", DEFAULT_MODEL)
    effort = session.get("effort", DEFAULT_EFFORT)
    turns = session.get("turn_count", 0)

    status_text = (
        "📊 *Status da Sessão Antigravity:*\n\n"
        f"• *Execução Ativa:* {'🟡 Em processamento...' if is_busy else '🟢 Livre / Pronta'}\n"
        f"• *Workspace:* `{workspace}`\n"
        f"• *Modelo:* `{model}`\n"
        f"• *Raciocínio (Effort):* `{effort}`\n"
        f"• *Turnos na Sessão:* `{turns}`\n"
        f"• *ID da Conversa:* `{conv_id}`\n"
    )
    send_formatted_response(bot, chat_id, status_text)


@bot.message_handler(commands=["pwd"])
def cmd_pwd(message):
    chat_id = message.chat.id
    if not is_authorized(chat_id):
        logger.warning(f"Acesso negado em /pwd: chat_id={chat_id}")
        bot.reply_to(message, f"⚠️ Acesso não autorizado. Seu chat ID é `{chat_id}`.", parse_mode="Markdown")
        return

    logger.info(f"[Chat {chat_id}] Executou /pwd")
    session = get_session(chat_id)
    ws = session.get("workspace", DEFAULT_WORKSPACE)

    if not os.path.exists(ws):
        send_formatted_response(bot, chat_id, f"⚠️ O diretório atual não existe: `{ws}`")
        return

    try:
        items = os.listdir(ws)
        items_sorted = sorted(items, key=lambda x: (not os.path.isdir(os.path.join(ws, x)), x.lower()))
        preview = []
        for it in items_sorted[:25]:
            full = os.path.join(ws, it)
            icon = "📁" if os.path.isdir(full) else "📄"
            preview.append(f"{icon} `{it}`")

        more = f"\n_... e mais {len(items) - 25} itens_" if len(items) > 25 else ""
        text = f"📁 *Diretório Atual:* `{ws}`\n\n*Conteúdo ({len(items)} itens):*\n" + "\n".join(preview) + more
        send_formatted_response(bot, chat_id, text)
    except Exception as e:
        send_formatted_response(bot, chat_id, f"❌ Erro ao listar diretório: `{e}`")


@bot.message_handler(commands=["cd", "workspace"])
def cmd_cd(message):
    chat_id = message.chat.id
    if not is_authorized(chat_id):
        logger.warning(f"Acesso negado em /cd: chat_id={chat_id}")
        bot.reply_to(message, f"⚠️ Acesso não autorizado. Seu chat ID é `{chat_id}`.", parse_mode="Markdown")
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        session = get_session(chat_id)
        ws = session.get("workspace", DEFAULT_WORKSPACE)
        send_formatted_response(bot, chat_id, f"📁 *Diretório atual:* `{ws}`\n\n_Para mudar, use:_ `/cd /caminho/do/projeto`")
        return

    target_path = parts[1].strip()
    session = get_session(chat_id)
    current_ws = session.get("workspace", DEFAULT_WORKSPACE)

    # Resolve caminho relativo ou com ~
    if target_path.startswith("~"):
        target_path = os.path.expanduser(target_path)
    elif not os.path.isabs(target_path):
        target_path = os.path.abspath(os.path.join(current_ws, target_path))
    else:
        target_path = os.path.abspath(target_path)

    if not os.path.exists(target_path):
        send_formatted_response(bot, chat_id, f"❌ Diretório não encontrado: `{target_path}`")
        return

    if not os.path.isdir(target_path):
        send_formatted_response(bot, chat_id, f"❌ O caminho informado não é um diretório: `{target_path}`")
        return

    update_session(chat_id, workspace=target_path)
    logger.info(f"[Chat {chat_id}] Alterou workspace para {target_path}")
    send_formatted_response(bot, chat_id, f"✅ *Diretório de trabalho alterado para:*\n`{target_path}`")


@bot.message_handler(commands=["models"])
def cmd_models(message):
    chat_id = message.chat.id
    if not is_authorized(chat_id):
        logger.warning(f"Acesso negado em /models: chat_id={chat_id}")
        bot.reply_to(message, f"⚠️ Acesso não autorizado. Seu chat ID é `{chat_id}`.", parse_mode="Markdown")
        return

    logger.info(f"[Chat {chat_id}] Executou /models")
    model_list_str = ""
    try:
        res = subprocess.run([AGY_PATH, "models"], capture_output=True, text=True, timeout=6)
        clean = re.sub(r'[\u2800-\u28ff]|Fetching available models\.\.\.', '', res.stdout).strip()
        lines = [l.strip() for l in clean.splitlines() if l.strip()]
        if lines:
            formatted = []
            for l in lines:
                parts = l.split(maxsplit=1)
                m_id = parts[0]
                m_desc = f" ({parts[1]})" if len(parts) > 1 else ""
                formatted.append(f"• `{m_id}`{m_desc}")
            model_list_str = "\n".join(formatted)
    except Exception as e:
        logger.warning(f"Falha ao consultar agy models: {e}")

    if not model_list_str:
        model_list_str = (
            "• `gemini-3.8-flash-high` (Padrão, rápido e de alta capacidade)\n"
            "• `gemini-3.8-flash-medium`\n"
            "• `gemini-3.7-flash-high`\n"
            "• `gemini-3.1-pro-high` (Máxima capacidade analítica)\n"
            "• `claude-sonnet-4-6` (Excelente para codificação e refatorações complexas)\n"
            "• `claude-opus-4-6-thinking`\n"
            "• `gpt-oss-120b-medium`"
        )

    session = get_session(chat_id)
    cur_model = session.get("model", DEFAULT_MODEL)

    msg = (
        f"🧠 *Modelos Disponíveis no Antigravity:*\n\n"
        f"{model_list_str}\n\n"
        f"📌 *Modelo Atual:* `{cur_model}`\n\n"
        f"_Para alterar, use:_ `/model <nome_do_modelo>`\n"
        f"_Exemplo:_ `/model claude-sonnet-4-6`"
    )
    send_formatted_response(bot, chat_id, msg)


def get_available_models():
    models = []
    try:
        res = subprocess.run([AGY_PATH, "models"], capture_output=True, text=True, timeout=6)
        clean = re.sub(r'[\u2800-\u28ff]|Fetching available models\.\.\.', '', res.stdout).strip()
        lines = [l.strip() for l in clean.splitlines() if l.strip()]
        for l in lines:
            parts = l.split(maxsplit=1)
            models.append(parts[0])
    except Exception:
        pass
    if not models:
        models = [
            "gemini-3.8-flash-high", "gemini-3.8-flash-medium", "gemini-3.7-flash-high",
            "gemini-3.1-pro-high", "claude-sonnet-4-6", "claude-opus-4-6-thinking", "gpt-oss-120b-medium"
        ]
    return models

@bot.message_handler(commands=["model"])
def cmd_set_model(message):
    chat_id = message.chat.id
    if not is_authorized(chat_id):
        logger.warning(f"Acesso negado em /model: chat_id={chat_id}")
        bot.reply_to(message, f"⚠️ Acesso não autorizado. Seu chat ID é `{chat_id}`.", parse_mode="Markdown")
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        session = get_session(chat_id)
        current_model = session.get("model", DEFAULT_MODEL)
        
        markup = InlineKeyboardMarkup()
        models = get_available_models()
        for m in models:
            text = f"✅ {m}" if m == current_model else m
            markup.add(InlineKeyboardButton(text, callback_data=f"set_model:{m}"))
            
        bot.reply_to(message, f"🧠 *Modelo atual:* `{current_model}`\n\nSelecione um modelo no painel abaixo:", reply_markup=markup, parse_mode="Markdown")
        return

    new_model = parts[1].strip().lower()
    update_session(chat_id, model=new_model)
    logger.info(f"[Chat {chat_id}] Alterou modelo para {new_model}")
    send_formatted_response(bot, chat_id, f"✅ *Modelo alterado para:* `{new_model}`")

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_model:'))
def callback_set_model(call):
    chat_id = call.message.chat.id
    if not is_authorized(chat_id):
        return
    model_name = call.data.split(':', 1)[1]
    update_session(chat_id, model=model_name)
    logger.info(f"[Chat {chat_id}] Alterou modelo via painel para {model_name}")
    try:
        bot.answer_callback_query(call.id, f"Modelo alterado para {model_name}")
        bot.edit_message_text(f"✅ *Modelo alterado para:* `{model_name}`", chat_id=chat_id, message_id=call.message.message_id, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Erro ao editar mensagem de modelo: {e}")


@bot.message_handler(commands=["effort"])
def cmd_effort(message):
    chat_id = message.chat.id
    if not is_authorized(chat_id):
        logger.warning(f"Acesso negado em /effort: chat_id={chat_id}")
        bot.reply_to(message, f"⚠️ Acesso não autorizado. Seu chat ID é `{chat_id}`.", parse_mode="Markdown")
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        session = get_session(chat_id)
        eff = session.get("effort", DEFAULT_EFFORT)
        send_formatted_response(bot, chat_id, f"⚡ *Nível de raciocínio atual:* `{eff}`\n\nOpções: `low`, `medium`, `high`\n_Exemplo:_ `/effort high`")
        return

    level = parts[1].strip().lower()
    if level not in ["low", "medium", "high"]:
        send_formatted_response(bot, chat_id, "❌ Nível inválido. Escolha entre: `low`, `medium` ou `high`.")
        return

    update_session(chat_id, effort=level)
    logger.info(f"[Chat {chat_id}] Alterou effort para {level}")
    send_formatted_response(bot, chat_id, f"✅ *Nível de raciocínio alterado para:* `{level}`")


@bot.message_handler(commands=["skills"])
def cmd_skills(message):
    chat_id = message.chat.id
    if not is_authorized(chat_id):
        logger.warning(f"Acesso negado em /skills: chat_id={chat_id}")
        bot.reply_to(message, f"⚠️ Acesso não autorizado. Seu chat ID é `{chat_id}`.", parse_mode="Markdown")
        return

    logger.info(f"[Chat {chat_id}] Executou /skills")
    try:
        res = subprocess.run([AGY_PATH, "-p", "/skills", "--output-format", "json"], capture_output=True, text=True, timeout=8)
        data = extract_agy_json(res.stdout)
        if data and data.get("response"):
            text = f"🧩 *Habilidades (Skills) do Antigravity:*\n\n{data['response']}"
            send_formatted_response(bot, chat_id, text)
            return
    except Exception as e:
        logger.warning(f"Erro ao consultar skills: {e}")

    send_formatted_response(bot, chat_id, "ℹ️ Nenhuma skill customizada ativa no momento.")



@bot.message_handler(commands=["restart"])
def cmd_restart(message):
    chat_id = message.chat.id
    if not is_authorized(chat_id):
        return
    logger.info(f"[Chat {chat_id}] Executou /restart")
    bot.reply_to(message, "🔄 *Reiniciando o processo do bot...*", parse_mode="Markdown")
    import sys
    os.execv(sys.executable, [sys.executable] + sys.argv)

@bot.message_handler(commands=["cancel"])
def cmd_cancel(message):
    chat_id = message.chat.id
    if not is_authorized(chat_id):
        logger.warning(f"Acesso negado em /cancel: chat_id={chat_id}")
        bot.reply_to(message, f"⚠️ Acesso não autorizado. Seu chat ID é `{chat_id}`.", parse_mode="Markdown")
        return

    logger.info(f"[Chat {chat_id}] Executou /cancel")
    with active_tasks_lock:
        task_info = active_tasks.get(chat_id)

    if not task_info:
        send_formatted_response(bot, chat_id, "ℹ️ Não há nenhuma execução em andamento no momento.")
        return

    process = task_info.get("process")
    if process and process.poll() is None:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            time.sleep(0.5)
            if process.poll() is None:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            logger.info(f"[Chat {chat_id}] Processo PID {process.pid} cancelado pelo usuário.")
        except Exception as e:
            logger.error(f"Erro ao matar processo: {e}")

    send_formatted_response(bot, chat_id, "🛑 *Execução cancelada com sucesso.*")


# ==========================================
# PROCESSAMENTO DE MENSAGENS (ANTIGRAVITY)
# ==========================================

def run_antigravity_task(chat_id: int, prompt: str, status_msg_id: int) -> None:
    """Executa o Antigravity em thread dedicada com typing indicator contínuo e tratamento de saída."""
    stop_typing = threading.Event()
    typing_th = threading.Thread(target=typing_worker, args=(bot, chat_id, stop_typing), daemon=True)
    typing_th.start()

    session = get_session(chat_id)
    workspace = session.get("workspace", DEFAULT_WORKSPACE)
    if not os.path.exists(workspace):
        workspace = BASE_DIR

    conv_id = session.get("conversation_id")
    model = session.get("model", DEFAULT_MODEL)
    effort = session.get("effort", DEFAULT_EFFORT)

    cmd = [
        AGY_PATH,
        "-p", prompt,
        "--dangerously-skip-permissions",
        "--output-format", "json",
        "--add-dir", workspace,
    ]

    if conv_id:
        cmd.extend(["--conversation", conv_id])
    if model:
        cmd.extend(["--model", model])
    if effort:
        cmd.extend(["--effort", effort])

    logger.info(f"[Chat {chat_id}] Executando: {' '.join(cmd[:6])}... em {workspace}")

    start_time = time.time()
    process = None

    try:
        process = subprocess.Popen(
            cmd,
            cwd=workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=os.setsid
        )

        with active_tasks_lock:
            active_tasks[chat_id] = {
                "process": process,
                "start_time": start_time,
                "stop_typing": stop_typing
            }

        stdout, stderr = process.communicate(timeout=TIMEOUT_SECONDS)
        elapsed = time.time() - start_time

    except subprocess.TimeoutExpired:
        if process:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except Exception:
                pass
        stop_typing.set()
        with active_tasks_lock:
            active_tasks.pop(chat_id, None)
        try:
            bot.delete_message(chat_id, status_msg_id)
        except Exception:
            pass
        send_formatted_response(bot, chat_id, f"⏱️ *Tempo limite esgotado ({TIMEOUT_SECONDS}s).* A tarefa demorou muito e foi cancelada.")
        return

    except Exception as e:
        stop_typing.set()
        with active_tasks_lock:
            active_tasks.pop(chat_id, None)
        try:
            bot.delete_message(chat_id, status_msg_id)
        except Exception:
            pass
        send_formatted_response(bot, chat_id, f"❌ *Erro ao executar Antigravity:* `{e}`")
        return

    finally:
        stop_typing.set()
        with active_tasks_lock:
            active_tasks.pop(chat_id, None)

    # Apaga a mensagem temporária de "Processando..."
    try:
        bot.delete_message(chat_id, status_msg_id)
    except Exception:
        pass

    # Processamento do resultado
    raw_combined = stdout if stdout else stderr
    parsed_json = extract_agy_json(stdout)

    if parsed_json:
        new_conv_id = parsed_json.get("conversation_id")
        current_turns = session.get("turn_count", 0) + 1
        
        usage_data = parsed_json.get("usage", {})
        turn_tokens = usage_data.get("total_tokens", 0)
        new_total_tokens = session.get("total_tokens", 0) + turn_tokens
        
        if new_conv_id:
            update_session(chat_id, conversation_id=new_conv_id, turn_count=current_turns, total_tokens=new_total_tokens)
        else:
            update_session(chat_id, turn_count=current_turns, total_tokens=new_total_tokens)

        response_text = parsed_json.get("response", "").strip()
        status = parsed_json.get("status", "SUCCESS")
        duration = parsed_json.get("duration_seconds", round(elapsed, 1))
        usage = parsed_json.get("usage", {})
        total_tokens = usage.get("total_tokens")

        footer_parts = [f"⏱️ `{duration:.1f}s`"]
        if total_tokens:
            footer_parts.append(f"🪙 `{total_tokens:,} tokens`".replace(",", "."))
        footer = " | ".join(footer_parts)

        if response_text:
            send_formatted_response(bot, chat_id, response_text, footer=f"—\n_{footer}_")
        elif "command" in parsed_json:
            cmd_info = parsed_json["command"]
            cmd_name = cmd_info.get("name", "comando")
            cmd_data = cmd_info.get("data", {})
            pretty_data = json.dumps(cmd_data, indent=2, ensure_ascii=False)
            send_formatted_response(bot, chat_id, f"ℹ️ *Comando `/{cmd_name}` executado:*\n```json\n{pretty_data}\n```", footer=f"—\n_{footer}_")
        elif status == "ERROR" and parsed_json.get("error"):
            err_msg = parsed_json.get("error")
            send_formatted_response(bot, chat_id, f"⚠️ *Erro retornado pelo Antigravity:*\n`{err_msg}`", footer=f"—\n_{footer}_")
        else:
            send_formatted_response(bot, chat_id, "✅ *Comando executado sem retorno textual.*", footer=f"—\n_{footer}_")

    else:
        clean_text = sanitize_text(raw_combined).strip()
        if not clean_text:
            clean_text = "✅ Comando executado sem retorno textual."
        footer = f"—\n_⏱️ `{elapsed:.1f}s`_"
        send_formatted_response(bot, chat_id, clean_text, footer=footer)


@bot.message_handler(func=lambda message: True)
def handle_incoming_prompt(message):
    chat_id = message.chat.id

    if not is_authorized(chat_id):
        logger.warning(f"Tentativa de acesso não autorizado: chat_id={chat_id}, username={getattr(message.from_user, 'username', 'desconhecido')}")
        bot.reply_to(message, f"⚠️ Acesso negado. Este bot é privado. Seu chat ID é `{chat_id}`.", parse_mode="Markdown")
        return

    prompt = message.text.strip()
    if not prompt:
        return

    logger.info(f"[Chat {chat_id}] Mensagem recebida: {prompt[:80]}...")

    with active_tasks_lock:
        if chat_id in active_tasks:
            bot.reply_to(
                message,
                "⚠️ *Já existe uma solicitação em andamento!*\nAguarde a conclusão ou envie `/cancel` para interromper.",
                parse_mode="Markdown"
            )
            return

    try:
        status_msg = bot.reply_to(message, "⏳ _Processando solicitação com o Antigravity..._", parse_mode="Markdown")
        status_msg_id = status_msg.message_id
    except Exception as e:
        logger.warning(f"Falha ao enviar mensagem de status: {e}")
        status_msg_id = 0

    th = threading.Thread(
        target=run_antigravity_task,
        args=(chat_id, prompt, status_msg_id),
        daemon=True
    )
    th.start()


def setup_bot_commands():
    """Configura o menu de comandos automáticos no Telegram."""
    try:
        commands = [
            BotCommand("start", "Apresentação e menu de ajuda"),
            BotCommand("help", "Lista de todos os comandos"),
            BotCommand("usage", "Ver o consumo de tokens e sistema"),
            BotCommand("status", "Ver status da sessão e workspace"),
            BotCommand("pwd", "Ver diretório atual e listar arquivos"),
            BotCommand("cd", "Alterar diretório de trabalho"),
            BotCommand("new", "Iniciar nova conversa / resetar"),
            BotCommand("models", "Listar modelos de IA disponíveis"),
            BotCommand("model", "Ver ou alterar modelo de IA"),
            BotCommand("effort", "Ajustar nível de raciocínio"),
            BotCommand("skills", "Listar habilidades disponíveis"),
            BotCommand("cancel", "Cancelar execução atual"),
            BotCommand("restart", "Reiniciar o processo do bot"),
        ]
        bot.set_my_commands(commands)
        logger.info("Menu de comandos configurado no Telegram com sucesso.")
    except Exception as e:
        logger.warning(f"Não foi possível registrar o menu de comandos no Telegram: {e}")


if __name__ == "__main__":
    logger.info("Iniciando Antigravity Telegram Bot...")
    setup_bot_commands()
    logger.info(f"Bot online! Chats autorizados: {ALLOWED_CHAT_IDS}. Workspace padrão: {DEFAULT_WORKSPACE}")

    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except Exception as e:
            logger.error(f"Erro no infinity_polling: {e}. Reiniciando conexão em 5s...")
            time.sleep(5)
