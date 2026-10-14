import discord
from discord.ext import commands, tasks
import logging
import logging.handlers
import sys
import socket
from config import (
    DISCORD_TOKEN, AUTHORIZED_USER_IDS, ALERT_CHANNEL_ID,
    DOCKER_CONTAINERS, SYSTEM_SERVICES, COMPOSE_PATHS,
    MONITOR_INTERVAL, LOG_LEVEL, LOG_FILE, MAX_LOG_SIZE, LOG_BACKUP_COUNT,
    validate_config
)
from monitor import (
    run_command, get_system_stats, check_docker_container,
    check_system_service, get_offline_services, check_health,
    generate_alerts, load_alert_history
)

# ========================
# LOGGING SETUP
# ========================

def setup_logging():
    """Configura logging para arquivo e console"""
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, LOG_LEVEL))
    
    # Handler para arquivo com rotação
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_LOG_SIZE,
        backupCount=LOG_BACKUP_COUNT
    )
    file_handler.setLevel(logging.DEBUG)
    
    # Handler para console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    
    # Formato
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logging()

# ========================
# DISCORD SETUP
# ========================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# ========================
# HELPERS
# ========================

def is_authorized(ctx) -> bool:
    """Verifica se usuário está autorizado"""
    return ctx.author.id in AUTHORIZED_USER_IDS

def validate_service(service: str) -> bool:
    """Valida se serviço existe"""
    return service in DOCKER_CONTAINERS or service in SYSTEM_SERVICES

def get_service_type(service: str) -> str:
    """Retorna tipo do serviço"""
    if service in DOCKER_CONTAINERS:
        return "docker"
    return "systemd"

async def add_reaction(message: discord.Message, success: bool) -> None:
    """Adiciona reação de feedback ao comando"""
    try:
        reaction = "✅" if success else "❌"
        await message.add_reaction(reaction)
    except Exception as e:
        logger.error(f"Erro ao adicionar reação: {e}")

# ========================
# EVENTS
# ========================

@bot.event
async def on_ready():
    """Bot conectado e pronto"""
    logger.info(f"Bot conectado como {bot.user}")
    logger.info(f"Ativo em {len(bot.guilds)} servidor(es)")
    health_monitor.start()
    logger.info("Monitor de saúde iniciado")

@bot.event
async def on_command_error(ctx, error):
    """Handler de erros de comando"""
    if isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title="❌ Erro de Sintaxe",
            description=f"Argumento faltando: `{error.param.name}`",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        logger.warning(f"Comando {ctx.command} executado sem argumento por {ctx.author}")
    
    elif isinstance(error, commands.CommandNotFound):
        embed = discord.Embed(
            title="❌ Comando Inválido",
            description="Use `!comandos` para ver os comandos disponíveis",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    
    else:
        logger.error(f"Erro no comando {ctx.command}: {error}")
        embed = discord.Embed(
            title="❌ Erro ao Executar",
            description=f"Erro: {str(error)[:100]}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

# ========================
# BASIC COMMANDS
# ========================

@bot.command(name="ping", help="Verifica latência do bot")
async def ping(ctx):
    """Teste de latência"""
    async with ctx.typing():
        latency = round(bot.latency * 1000)
        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"Latência: **{latency}ms**",
            color=discord.Color.green()
        )
        msg = await ctx.send(embed=embed)
        await add_reaction(msg, True)
        logger.info(f"Comando ping executado por {ctx.author}")

@bot.command(name="ip", help="Obtém IP do servidor")
async def ip(ctx):
    """Mostra IP do servidor"""
    async with ctx.typing():
        try:
            hostname = socket.gethostname()
            ip_addr = socket.gethostbyname(hostname)
            
            embed = discord.Embed(
                title="🌐 IP do Servidor",
                description=f"`{ip_addr}`",
                color=discord.Color.blue()
            )
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, True)
            logger.info(f"IP obtido por {ctx.author}: {ip_addr}")
        except Exception as e:
            logger.error(f"Erro ao obter IP: {e}")
            embed = discord.Embed(
                title="❌ Erro",
                description=f"Não foi possível obter IP: {str(e)[:100]}",
                color=discord.Color.red()
            )
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, False)

# ========================
# MONITORING COMMANDS
# ========================

@bot.command(name="server", help="Status completo do servidor")
async def server(ctx):
    """Mostra status do servidor"""
    async with ctx.typing():
        try:
            stats = get_system_stats()
            
            embed = discord.Embed(
                title="📊 Status do Servidor",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            
            # CPU
            cpu_color = "🔴" if stats['cpu'] >= 80 else "🟡" if stats['cpu'] >= 50 else "🟢"
            embed.add_field(
                name=f"{cpu_color} CPU",
                value=f"```{stats['cpu']}%```",
                inline=True
            )
            
            # RAM
            ram_color = "🔴" if stats['ram'] >= 80 else "🟡" if stats['ram'] >= 50 else "🟢"
            embed.add_field(
                name=f"{ram_color} RAM",
                value=f"```{stats['ram']}%```",
                inline=True
            )
            
            # DISK
            disk_color = "🔴" if stats['disk'] >= 90 else "🟡" if stats['disk'] >= 80 else "🟢"
            embed.add_field(
                name=f"{disk_color} DISCO",
                value=f"```{stats['disk']}%```",
                inline=True
            )
            
            # TEMP
            if isinstance(stats['temp'], (int, float)):
                temp_color = "🔴" if stats['temp'] >= 80 else "🟡" if stats['temp'] >= 60 else "🟢"
                embed.add_field(
                    name=f"{temp_color} TEMPERATURA",
                    value=f"```{stats['temp']}°C```",
                    inline=True
                )
            
            # INTERNET
            internet_icon = "✅" if stats['internet'] else "❌"
            embed.add_field(
                name=f"{internet_icon} INTERNET",
                value=f"```{'ONLINE' if stats['internet'] else 'OFFLINE'}```",
                inline=True
            )
            
            # UPTIME
            embed.add_field(
                name="⏱️ UPTIME",
                value=f"```{stats['uptime']}```",
                inline=False
            )
            
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, True)
            logger.info(f"Status do servidor solicitado por {ctx.author}")
        except Exception as e:
            logger.error(f"Erro ao obter status: {e}")
            embed = discord.Embed(
                title="❌ Erro",
                description=f"Erro ao obter status: {str(e)[:100]}",
                color=discord.Color.red()
            )
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, False)

@bot.command(name="health", help="Verificação completa de saúde")
async def health(ctx):
    """Verificação completa de saúde"""
    async with ctx.typing():
        try:
            health_data = check_health()
            offline = health_data['offline_services']
            
            has_problems = (
                health_data['cpu'] >= 80 or
                health_data['ram'] >= 80 or
                health_data['disk'] >= 90 or
                offline or
                not health_data['internet']
            )
            
            color = discord.Color.red() if has_problems else discord.Color.green()
            
            embed = discord.Embed(
                title="❤️ Saúde do Homelab",
                color=color,
                timestamp=discord.utils.utcnow()
            )
            
            # Recursos
            cpu_icon = "🔴" if health_data['cpu'] >= 80 else "🟡" if health_data['cpu'] >= 50 else "🟢"
            ram_icon = "🔴" if health_data['ram'] >= 80 else "🟡" if health_data['ram'] >= 50 else "🟢"
            disk_icon = "🔴" if health_data['disk'] >= 90 else "🟡" if health_data['disk'] >= 80 else "🟢"
            
            resources = f"{cpu_icon} CPU: {health_data['cpu']}% | {ram_icon} RAM: {health_data['ram']}% | {disk_icon} DISCO: {health_data['disk']}%"
            embed.add_field(name="📈 Recursos", value=resources, inline=False)
            
            # Temperatura
            if isinstance(health_data['temp'], (int, float)):
                temp_icon = "🔴" if health_data['temp'] >= 80 else "🟡" if health_data['temp'] >= 60 else "🟢"
                embed.add_field(name="🌡️ Temperatura", value=f"{temp_icon} {health_data['temp']}°C", inline=True)
            
            # Internet
            internet_icon = "✅" if health_data['internet'] else "❌"
            embed.add_field(name="🌐 Internet", value=f"{internet_icon} {'ONLINE' if health_data['internet'] else 'OFFLINE'}", inline=True)
            
            # Serviços
            if offline:
                embed.add_field(
                    name="⚠️ SERVIÇOS OFFLINE",
                    value=f"```{', '.join(offline)}```",
                    inline=False
                )
            else:
                embed.add_field(
                    name="✅ Serviços",
                    value="Todos os serviços estão online",
                    inline=False
                )
            
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, not has_problems)
            logger.info(f"Health check solicitado por {ctx.author}")
        except Exception as e:
            logger.error(f"Erro na verificação de saúde: {e}")
            embed = discord.Embed(
                title="❌ Erro",
                description=f"Erro ao verificar saúde: {str(e)[:100]}",
                color=discord.Color.red()
            )
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, False)

@bot.command(name="docker", help="Lista containers Docker")
async def docker(ctx):
    """Lista containers Docker"""
    async with ctx.typing():
        try:
            result = run_command([
                "docker", "ps",
                "--format", "table {{.Names}}\t{{.Status}}"
            ])
            
            if result:
                embed = discord.Embed(
                    title="🐳 Docker Containers",
                    description=f"```{result}```",
                    color=discord.Color.blue()
                )
                msg = await ctx.send(embed=embed)
                await add_reaction(msg, True)
            else:
                embed = discord.Embed(
                    title="❌ Erro",
                    description="Não foi possível listar containers",
                    color=discord.Color.red()
                )
                msg = await ctx.send(embed=embed)
                await add_reaction(msg, False)
            
            logger.info(f"Containers listados por {ctx.author}")
        except Exception as e:
            logger.error(f"Erro ao listar docker: {e}")
            embed = discord.Embed(
                title="❌ Erro",
                description=f"Erro: {str(e)[:100]}",
                color=discord.Color.red()
            )
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, False)

@bot.command(name="temp", help="Temperatura do CPU")
async def temp(ctx):
    """Mostra temperatura"""
    async with ctx.typing():
        try:
            temp = get_system_stats()['temp']
            
            if isinstance(temp, (int, float)):
                color = discord.Color.red() if temp >= 80 else discord.Color.orange() if temp >= 60 else discord.Color.green()
                icon = "🔴" if temp >= 80 else "🟡" if temp >= 60 else "🟢"
                embed = discord.Embed(
                    title=f"{icon} Temperatura do CPU",
                    description=f"```{temp}°C```",
                    color=color
                )
            else:
                embed = discord.Embed(
                    title="⚠️ Temperatura",
                    description="Não disponível",
                    color=discord.Color.greyple()
                )
            
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, True)
            logger.info(f"Temperatura solicitada por {ctx.author}")
        except Exception as e:
            logger.error(f"Erro ao obter temperatura: {e}")
            embed = discord.Embed(
                title="❌ Erro",
                description=f"Erro: {str(e)[:100]}",
                color=discord.Color.red()
            )
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, False)

# ========================
# SERVICE CONTROL COMMANDS
# ========================

@bot.command(name="status", help="Status de um serviço")
async def status(ctx, service: str = None):
    """Mostra status de um serviço"""
    if not service:
        embed = discord.Embed(
            title="❌ Erro de Sintaxe",
            description="Use: `!status <serviço>`",
            color=discord.Color.red()
        )
        msg = await ctx.send(embed=embed)
        await add_reaction(msg, False)
        return
    
    if not validate_service(service):
        embed = discord.Embed(
            title="❌ Serviço Inválido",
            description=f"Serviço `{service}` não encontrado",
            color=discord.Color.red()
        )
        msg = await ctx.send(embed=embed)
        await add_reaction(msg, False)
        return
    
    async with ctx.typing():
        try:
            service_type = get_service_type(service)
            
            if service_type == "docker":
                is_running, error = check_docker_container(service)
            else:
                is_running, error = check_system_service(service)
            
            status_str = "🟢 ATIVO" if is_running else "🔴 OFFLINE"
            color = discord.Color.green() if is_running else discord.Color.red()
            
            embed = discord.Embed(
                title=f"Status: {service}",
                description=f"{status_str}",
                color=color
            )
            
            if not is_running and error:
                embed.add_field(name="Erro", value=f"```{error}```", inline=False)
            
            embed.add_field(name="Tipo", value=service_type, inline=True)
            
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, is_running)
            logger.info(f"Status de {service} solicitado por {ctx.author}")
        except Exception as e:
            logger.error(f"Erro ao verificar status: {e}")
            embed = discord.Embed(
                title="❌ Erro",
                description=f"Erro: {str(e)[:100]}",
                color=discord.Color.red()
            )
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, False)

@bot.command(name="restart", help="Reinicia um serviço")
async def restart(ctx, service: str = None):
    """Reinicia um serviço"""
    if not is_authorized(ctx):
        embed = discord.Embed(
            title="❌ Permissão Negada",
            description="Você não tem permissão para executar este comando",
            color=discord.Color.red()
        )
        msg = await ctx.send(embed=embed)
        await add_reaction(msg, False)
        return
    
    if not service:
        embed = discord.Embed(
            title="❌ Erro de Sintaxe",
            description="Use: `!restart <serviço>`",
            color=discord.Color.red()
        )
        msg = await ctx.send(embed=embed)
        await add_reaction(msg, False)
        return
    
    if not validate_service(service):
        embed = discord.Embed(
            title="❌ Serviço Inválido",
            description=f"Serviço `{service}` não encontrado",
            color=discord.Color.red()
        )
        msg = await ctx.send(embed=embed)
        await add_reaction(msg, False)
        return
    
    async with ctx.typing():
        try:
            service_type = get_service_type(service)
            
            if service_type == "docker":
                run_command(["docker", "restart", DOCKER_CONTAINERS[service]])
            else:
                run_command(["sudo", "systemctl", "restart", SYSTEM_SERVICES[service]])
            
            embed = discord.Embed(
                title=f"✅ {service} Reiniciado",
                color=discord.Color.green()
            )
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, True)
            logger.warning(f"Serviço {service} reiniciado por {ctx.author}")
        except Exception as e:
            logger.error(f"Erro ao reiniciar {service}: {e}")
            embed = discord.Embed(
                title="❌ Erro",
                description=f"Erro ao reiniciar: {str(e)[:100]}",
                color=discord.Color.red()
            )
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, False)

@bot.command(name="stop", help="Para um serviço")
async def stop(ctx, service: str = None):
    """Para um serviço"""
    if not is_authorized(ctx):
        embed = discord.Embed(
            title="❌ Permissão Negada",
            color=discord.Color.red()
        )
        msg = await ctx.send(embed=embed)
        await add_reaction(msg, False)
        return
    
    if not service:
        embed = discord.Embed(
            title="❌ Erro de Sintaxe",
            description="Use: `!stop <serviço>`",
            color=discord.Color.red()
        )
        msg = await ctx.send(embed=embed)
        await add_reaction(msg, False)
        return
    
    if not validate_service(service):
        embed = discord.Embed(
            title="❌ Serviço Inválido",
            description=f"Serviço `{service}` não encontrado",
            color=discord.Color.red()
        )
        msg = await ctx.send(embed=embed)
        await add_reaction(msg, False)
        return
    
    async with ctx.typing():
        try:
            service_type = get_service_type(service)
            
            if service_type == "docker":
                run_command(["docker", "stop", DOCKER_CONTAINERS[service]])
            else:
                run_command(["sudo", "systemctl", "stop", SYSTEM_SERVICES[service]])
            
            embed = discord.Embed(
                title=f"⏹️ {service} Parado",
                color=discord.Color.orange()
            )
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, True)
            logger.warning(f"Serviço {service} parado por {ctx.author}")
        except Exception as e:
            logger.error(f"Erro ao parar {service}: {e}")
            embed = discord.Embed(
                title="❌ Erro",
                description=f"Erro: {str(e)[:100]}",
                color=discord.Color.red()
            )
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, False)

@bot.command(name="start", help="Inicia um serviço")
async def start(ctx, service: str = None):
    """Inicia um serviço"""
    if not is_authorized(ctx):
        embed = discord.Embed(
            title="❌ Permissão Negada",
            color=discord.Color.red()
        )
        msg = await ctx.send(embed=embed)
        await add_reaction(msg, False)
        return
    
    if not service:
        embed = discord.Embed(
            title="❌ Erro de Sintaxe",
            description="Use: `!start <serviço>`",
            color=discord.Color.red()
        )
        msg = await ctx.send(embed=embed)
        await add_reaction(msg, False)
        return
    
    if not validate_service(service):
        embed = discord.Embed(
            title="❌ Serviço Inválido",
            description=f"Serviço `{service}` não encontrado",
            color=discord.Color.red()
        )
        msg = await ctx.send(embed=embed)
        await add_reaction(msg, False)
        return
    
    async with ctx.typing():
        try:
            service_type = get_service_type(service)
            
            if service_type == "docker":
                run_command(["docker", "start", DOCKER_CONTAINERS[service]])
            else:
                run_command(["sudo", "systemctl", "start", SYSTEM_SERVICES[service]])
            
            embed = discord.Embed(
                title=f"▶️ {service} Iniciado",
                color=discord.Color.green()
            )
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, True)
            logger.warning(f"Serviço {service} iniciado por {ctx.author}")
        except Exception as e:
            logger.error(f"Erro ao iniciar {service}: {e}")
            embed = discord.Embed(
                title="❌ Erro",
                description=f"Erro: {str(e)[:100]}",
                color=discord.Color.red()
            )
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, False)

# ========================
# SYSTEM CONTROL
# ========================

@bot.command(name="reboot", help="Reinicia o servidor")
async def reboot(ctx):
    """Reinicia o servidor"""
    if not is_authorized(ctx):
        embed = discord.Embed(
            title="❌ Permissão Negada",
            color=discord.Color.red()
        )
        msg = await ctx.send(embed=embed)
        await add_reaction(msg, False)
        return
    
    try:
        embed = discord.Embed(
            title="🔄 Reiniciando Servidor",
            description="O servidor será reiniciado em breve...",
            color=discord.Color.red()
        )
        msg = await ctx.send(embed=embed)
        await add_reaction(msg, True)
        logger.critical(f"Reboot iniciado por {ctx.author}")
        run_command(["sudo", "reboot"])
    except Exception as e:
        logger.error(f"Erro ao reiniciar: {e}")
        embed = discord.Embed(
            title="❌ Erro",
            description=f"Erro: {str(e)[:100]}",
            color=discord.Color.red()
        )
        msg = await ctx.send(embed=embed)
        await add_reaction(msg, False)

@bot.command(name="compose", help="Lista caminhos do docker-compose")
async def compose(ctx):
    """Lista caminhos do compose"""
    async with ctx.typing():
        try:
            text = ""
            for name, path in COMPOSE_PATHS.items():
                text += f"{name}: `{path}`\n"
            
            embed = discord.Embed(
                title="📁 Docker Compose Paths",
                description=text,
                color=discord.Color.blue()
            )
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, True)
            logger.info(f"Compose paths listados por {ctx.author}")
        except Exception as e:
            logger.error(f"Erro ao listar compose: {e}")
            embed = discord.Embed(
                title="❌ Erro",
                description=f"Erro: {str(e)[:100]}",
                color=discord.Color.red()
            )
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, False)

@bot.command(name="history", help="Histórico de alertas")
async def history(ctx, limit: int = 10):
    """Mostra histórico de alertas"""
    async with ctx.typing():
        try:
            alerts = load_alert_history()[-limit:]
            
            if not alerts:
                embed = discord.Embed(
                    title="📋 Histórico de Alertas",
                    description="Nenhum alerta registrado",
                    color=discord.Color.green()
                )
            else:
                text = ""
                for alert in reversed(alerts):
                    timestamp = alert['timestamp'][:16]
                    text += f"[{timestamp}] {alert['message']}\n"
                
                # Trunca se muito longo
                if len(text) > 2000:
                    text = text[:1900] + "\n... (truncado)"
                
                embed = discord.Embed(
                    title="📋 Histórico de Alertas",
                    description=f"```{text}```",
                    color=discord.Color.blue()
                )
            
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, True)
            logger.info(f"Histórico de alertas solicitado por {ctx.author}")
        except Exception as e:
            logger.error(f"Erro ao carregar histórico: {e}")
            embed = discord.Embed(
                title="❌ Erro",
                description=f"Erro: {str(e)[:100]}",
                color=discord.Color.red()
            )
            msg = await ctx.send(embed=embed)
            await add_reaction(msg, False)

# ========================
# HELP COMMAND
# ========================

@bot.command(name="comandos", help="Lista todos os comandos disponíveis")
async def comandos(ctx):
    """Mostra lista de comandos"""
    embed = discord.Embed(
        title="📋 Comandos Disponíveis",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    
    embed.add_field(
        name="📊 INFORMAÇÕES",
        value=
            "`!ping` - Latência do bot\n"
            "`!server` - Status do servidor\n"
            "`!health` - Saúde completa\n"
            "`!docker` - Containers Docker\n"
            "`!temp` - Temperatura CPU\n"
            "`!ip` - IP do servidor\n"
            "`!compose` - Caminhos compose\n"
            "`!history [limite]` - Histórico de alertas",
        inline=False
    )
    
    embed.add_field(
        name="⚙️ CONTROLE (requer permissão)",
        value=
            "`!status <serviço>` - Status de um serviço\n"
            "`!restart <serviço>` - Reinicia serviço\n"
            "`!start <serviço>` - Inicia serviço\n"
            "`!stop <serviço>` - Para serviço\n"
            "`!reboot` - Reinicia servidor",
        inline=False
    )
    
    embed.add_field(
        name="🐳 SERVIÇOS DOCKER",
        value=", ".join([f"`{s}`" for s in DOCKER_CONTAINERS.keys()]),
        inline=False
    )
    
    embed.add_field(
        name="🔧 SERVIÇOS SYSTEMD",
        value=", ".join([f"`{s}`" for s in SYSTEM_SERVICES.keys()]),
        inline=False
    )
    
    embed.set_footer(text="Use !help <comando> para mais informações")
    
    msg = await ctx.send(embed=embed)
    await add_reaction(msg, True)
    logger.info(f"Comandos solicitados por {ctx.author}")

# ========================
# MONITORING
# ========================

@tasks.loop(minutes=MONITOR_INTERVAL)
async def health_monitor():
    """Loop de monitoramento periódico"""
    try:
        channel = bot.get_channel(ALERT_CHANNEL_ID)
        if not channel:
            logger.warning("Canal de alertas não encontrado")
            return
        
        alerts = generate_alerts()
        
        if alerts:
            embed = discord.Embed(
                title="⚠️ ALERTAS DO HOMELAB",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            
            alert_text = "\n".join(alerts)
            embed.description = alert_text
            
            msg = await channel.send(embed=embed)
            logger.warning(f"{len(alerts)} alerta(s) enviado(s)")
    
    except Exception as e:
        logger.error(f"Erro no monitor de saúde: {e}")

# ========================
# START
# ========================

if __name__ == "__main__":
    try:
        validate_config()
        logger.info("✅ Configurações validadas com sucesso")
        logger.info("🚀 Iniciando bot...")
        bot.run(DISCORD_TOKEN)
    except ValueError as e:
        logger.critical(f"❌ Erro de configuração: {e}")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"❌ Erro fatal: {e}")
        sys.exit(1)