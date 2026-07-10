import logging
from typing import Optional
import asyncssh
from bot.config import config

logger = logging.getLogger(__name__)

class StrongSwanClient:
    def __init__(self):
        self.host = config.SSH_HOST
        self.port = config.SSH_PORT
        self.user = config.SSH_USER
        self.key_path = config.SSH_KEY_PATH

    async def _execute_command(self, command: str) -> Optional[str]:
        """Внутренний метод для безопасного асинхронного выполнения bash-команд по SSH"""
        if not config.ENABLE_STRONGSWAN or not self.host:
            logger.warning("Интеграция со StrongSwan отключена в конфигурации.")
            return None

        try:
            # Подключаемся по SSH-ключу, указанному в конфиге
            async with asyncssh.connect(
                self.host, 
                port=self.port, 
                username=self.user, 
                client_keys=[self.key_path] if self.key_path else None
            ) as conn:
                result = await conn.run(command, check=True)
                return result.stdout
        except Exception as e:
            logger.error(f"Ошибка выполнения SSH-команды '{command}': {e}")
            return None

    async def add_user(self, login: str, password: str) -> bool:
        """
        Добавляет нового пользователя в ipsec.secrets.
        Формат записи: login : EAP "password"
        """
        # Экранируем спецсимволы в пароле и добавляем строку в конец файла
        cmd = f'echo \'{login} : EAP "{password}"\' >> /etc/ipsec.secrets && ipsec rereadsecrets'
        
        # Если вы используете современный swanctl (StrongSwan 5.9+):
        # cmd = f'echo "connections {{ eap-{login} {{ secrets {{ eap-{login} {{ id = {login}; secret = {password}; }} }} }} }}" >> /etc/swanctl/conf.d/users.conf && swanctl --reload'
        
        result = await self._execute_command(cmd)
        return result is not None

    async def delete_user(self, login: str) -> bool:
        """Полностью удаляет пользователя из конфигурации по логину"""
        # Удаляем строку, содержащую логин пользователя из файла secrets
        cmd = f"sed -i '/^{login} /d' /etc/ipsec.secrets && ipsec rereadsecrets"
        result = await self._execute_command(cmd)
        return result is not None

    async def set_user_status(self, login: str, password: str, enable: bool) -> bool:
        """
        Включает или выключает пользователя.
        Для выключения мы просто комментируем его строку знаком #, для включения — раскомментируем.
        """
        if enable:
            # Убираем знак комментария # перед логином, если он там был
            cmd = f"sed -i 's/^#{login}/{login}/' /etc/ipsec.secrets && ipsec rereadsecrets"
        else:
            # Ставим знак комментария # в начало строки с логином
            cmd = f"sed -i 's/^{login}/#{login}/' /etc/ipsec.secrets && ipsec rereadsecrets"
            
        result = await self._execute_command(cmd)
        return result is not None

# Экспортируем готовый экземпляр клиента
strongswan_client = StrongSwanClient()
