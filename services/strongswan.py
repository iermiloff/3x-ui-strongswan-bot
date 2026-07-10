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
        Создает изолированный файл конфигурации для пользователя в swanctl.
        Путь на сервере: /etc/swanctl/conf.d/user_{login}.conf
        """
        file_path = f"/etc/swanctl/conf.d/user_{login}.conf"
        
        # Формируем структуру конфига swanctl для EAP-аутентификации
        config_content = (
            f"secrets {{\n"
            f"    eap-{login} {{\n"
            f"        id = {login}\n"
            f"        secret = \"{password}\"\n"
            f"    }}\n"
            f"}}\n"
        )
        
        # Записываем контент в файл и перезагружаем пул конфигураций swanctl
        cmd = f"echo '{config_content}' > {file_path} && swanctl --reload"
        result = await self._execute_command(cmd)
        return result is not None

    async def delete_user(self, login: str) -> bool:
        """Полностью удаляет файл конфигурации пользователя"""
        file_path = f"/etc/swanctl/conf.d/user_{login}.conf"
        cmd = f"rm -f {file_path} && swanctl --reload"
        result = await self._execute_command(cmd)
        return result is not None

    async def set_user_status(self, login: str, password: str, enable: bool) -> bool:
        """
        Включает или выключает пользователя.
        Для выключения мы переименовываем файл (добавляем .disabled), чтобы swanctl его игнорировал.
        """
        active_path = f"/etc/swanctl/conf.d/user_{login}.conf"
        disabled_path = f"/etc/swanctl/conf.d/user_{login}.conf.disabled"
        
        if enable:
            # Возвращаем файл в активное состояние, если он был отключен
            cmd = f"[ -f {disabled_path} ] && mv {disabled_path} {active_path} && swanctl --reload || true"
        else:
            # Переименовываем активный файл в .disabled
            cmd = f"[ -f {active_path} ] && mv {active_path} {disabled_path} && swanctl --reload || true"
            
        result = await self._execute_command(cmd)
        return result is not None

# Экспортируем готовый экземпляр клиента
strongswan_client = StrongSwanClient()
