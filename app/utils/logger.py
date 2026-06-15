import logging
import pathlib
from agno.utils.log import configure_agno_logging

# 1. Preparar pastas
logs_path = pathlib.Path.cwd() / "logs"
logs_path.mkdir(parents=True, exist_ok=True)

# 2. Criar o Formatador Colorido Inteligente para o Terminal
class CoresDoTerminalFormatter(logging.Formatter):
    RESET = "\033[0m"
    CORES = {
        logging.DEBUG: "\033[34m[DEBUG]\033[0m",     # Azul
        logging.INFO: "[INFO]",                      # Sem cor (padrão)
        logging.WARNING: "\033[33m[WARNING]\033[0m", # Amarelo
        logging.ERROR: "\033[31m[ERROR]\033[0m",     # Vermelho
        logging.CRITICAL: "\033[41m[CRITICAL]\033[0m" # Fundo Vermelho
    }

    def format(self, record):
        # Captura o prefixo colorido baseado no nível do log
        prefixo = self.CORES.get(record.levelno, "[LOG]")
        # Define o formato usando o prefixo correspondente
        self._style._fmt = f"{prefixo} %(levelname)s: %(message)s"
        return super().format(record)

# 3. Configurar o Logger Único do Sistema
meu_logger = logging.getLogger("agno_custom_logger")
meu_logger.setLevel(logging.DEBUG) # Captura absolutamente TUDO
meu_logger.propagate = False

# Handler 1: Terminal (Com as cores dinâmicas)
console_handler = logging.StreamHandler()
console_handler.setFormatter(CoresDoTerminalFormatter())
meu_logger.addHandler(console_handler)

# Handler 2: Arquivo (Salva APENAS erros no arquivo 'error.log')
arquivo_error_handler = logging.FileHandler(logs_path / "error.log", mode="a", encoding="utf-8")
arquivo_error_handler.setLevel(logging.ERROR) # Filtra para salvar só Erros/Críticos aqui
arquivo_formatter = logging.Formatter("[ERROR] %(asctime)s - %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
arquivo_error_handler.setFormatter(arquivo_formatter)
meu_logger.addHandler(arquivo_error_handler)

# 4. Configurar o Agno UMA ÚNICA VEZ para usar esse super logger
configure_agno_logging(custom_default_logger=meu_logger)