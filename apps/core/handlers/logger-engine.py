import logging
from datetime import datetime

import pytz


class LoggerEngine:
    """Centraliza o registro de logs da aplicação com origem configurável.

    A classe encapsula a configuração básica do logger, define os níveis de
    log aceitos e formata a data/hora no fuso horário de São Paulo para ser
    incluída nas mensagens registradas.

    Meu objetivo aqui é simular traces de execução como costumamos usar no CloudWatch,
    para facilitar o monitoramento e a depuração da aplicação.
    """

    def __init__(self, origin: str = None):
        """Inicializa o logger com uma origem padrão ou personalizada.

        Args:
            origin: Identificador da origem da mensagem. Quando não informado,
                utiliza ``BACKEND``.
        """
        self.origin = "BACKEND" if origin is None else origin
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        formatar = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%d/%m/%Y %H:%M:%S",
        )
        if not self.logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatar)
            self.logger.addHandler(console_handler)

        self.LOG_LEVELS = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }

    def registrar(self, message, level="ERROR"):
        """Registra uma mensagem no nível informado.

        Args:
            message: Conteúdo que será enviado para o logger.
            level: Nível de severidade desejado. Caso seja inválido, o método
                faz fallback para ``ERROR`` e registra a inconsistência.

        Returns:
            A mensagem efetivamente registrada, incluindo o texto de erro em
            caso o nível informado não seja suportado.
        """
        if level not in self.LOG_LEVELS:
            level = "ERROR"
            message = f"O nível de log informado não é válido: {message}"
            self.logger.error(message)
        else:
            self.logger.log(
                self.LOG_LEVELS[level],
                "[%s] - [%s] %s: %s",
                self.origin,
                self._get_formatted_time(),
                level,
                message,
                extra={},
            )
        return message

    def _get_formatted_time(self):
        """Retorna a data e hora atual formatada no fuso de São Paulo."""
        utc3_timezone = pytz.timezone("America/Sao_Paulo")
        current_time = datetime.now(utc3_timezone)
        return current_time.strftime("%d/%m/%Y %H:%M:%S")
