import logging
import asyncssh  # Проверьте импорт библиотеки, которая у вас используется в проекте (async_ssh или paramiko)
from bot.config import config

logger = logging.getLogger(__name__)

class StrongSwanClient:
    def __init__(self):
        self.host = config.SSH_HOST
        self.user = config.SSH_USER
        self.password = config.SSH_PASSWORD
        self.secrets_path = "/etc/ipsec.secrets"

    async def _execute_ssh_cmd(self, command: str) -> bool:
        """Выполнение быстрой команды на удаленной VPN-ноде по SSH"""
        try:
            async with asyncssh.connect(self.host, username=self.user, password=self.password) as conn:
                result = await conn.run(command)
                return result.exit_status == 0
        except Exception as e:
            logger.error(f"Ошибка выполнения удаленной SSH-команды на VPN-ноде: {e}")
            return False

    async def add_user(self, login: str, password: str) -> bool:
        """
        [ОПЛАТА]: Дописывает пользователя в конец файла secrets 
        и мгновенно перечитывает ОЗУ на лету (активные сессии не рвутся!).
        """
        line = f'{login} : EAP "{password}"'
        cmd = f"echo '{line}' | sudo tee -a {self.secrets_path} && sudo ipsec rereadsecrets"
        
        success = await self._execute_ssh_cmd(cmd)
        if success:
            logger.info(f"✅ Пользователь IKEv2 {login} успешно добавлен на удаленную ноду.")
        return success

    async def set_user_status(self, login: str, password: str, enable: bool) -> bool:
        """
        [БЛОКИРОВКА / АКТИВАЦИЯ]: Комментирует строку (#) при выключении 
        или убирает решетку обратно с помощью sed.
        """
        if enable:
            # Убираем решетку комментария
            cmd = f"sudo sed -i 's/^#\\s*{login} :/{login} :/' {self.secrets_path} && sudo ipsec rereadsecrets"
        else:
            # Ставим решетку комментария (блокируем доступ)
            cmd = f"sudo sed -i 's/^{login} :/# {login} :/' {self.secrets_path} && sudo ipsec rereadsecrets"
            
        return await self._execute_ssh_cmd(cmd)

    async def delete_user(self, login: str) -> bool:
        """
        [УДАЛЕНИЕ]: Навсегда вырезает строки с пользователем из файла secrets.
        """
        cmd = f"sudo sed -i '/^{login} :/d' {self.secrets_path} && sudo sed -i '/^#\\s*{login} :/d' {self.secrets_path} && sudo ipsec rereadsecrets"
        return await self._execute_ssh_cmd(cmd)

strongswan_client = StrongSwanClient()

