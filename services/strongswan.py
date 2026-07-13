import logging
import asyncssh
from bot.config import config

logger = logging.getLogger(__name__)

class StrongSwanClient:
    def __init__(self):
        self.host = config.SSH_HOST
        self.port = config.SSH_PORT or 22
        self.user = config.SSH_USER
        self.password = config.SSH_PASSWORD  # Работаем по паролю
        self.secrets_path = "/etc/ipsec.secrets"

    async def _execute_ssh_cmd(self, command: str) -> bool:
        """Выполнение быстрой команды на удаленной VPN-ноде по SSH-паролю"""
        try:
            # Отключаем строгую проверку known_hosts, чтобы бот не падал при первом коннекте к новому серверу
            async with asyncssh.connect(
                self.host, 
                port=self.port,
                username=self.user, 
                password=self.password,
                known_hosts=None
            ) as conn:
                result = await conn.run(command)
                return result.exit_status == 0
        except Exception as e:
            logger.error(f"Ошибка выполнения удаленной SSH-команды на VPN-ноде: {e}")
            return False

        async def check_connection(self) -> bool:
        """
        [СТАРТ]: Проверка первичного SSH-доступа к удаленной VPN-ноде.
        Возвращает True, если авторизация успешна, иначе логирует точную ошибку.
        """
        if not config.ENABLE_STRONGSWAN:
            logger.info("ℹ️ Интеграция со StrongSwan отключена в конфиге.")
            return True
            
        try:
            async with asyncssh.connect(
                self.host, 
                port=self.port,
                username=self.user, 
                password=self.password,
                known_hosts=None,
                login_timeout=10.0
            ) as conn:
                # Пробуем выполнить легкую тестовую команду, чтобы убедиться в правах root
                result = await conn.run("id")
                if result.exit_status == 0:
                    logger.info(f"✨ [SSH] Успешное подключение к VPN-ноде {self.host}! Доступ авторизован.")
                    return True
                else:
                    logger.error(f"❌ [SSH] Ошибка прав на VPN-ноде: {result.stderr}")
                    return False
        except asyncssh.PermissionDenied:
            logger.error(f"❌ [SSH] КРИТИЧЕСКАЯ ОШИБКА: Отказано в доступе к {self.host}. Неверный SSH_USER или SSH_PASSWORD!")
            return False
        except (OSError, ConnectionRefusedError):
            logger.error(f"❌ [SSH] КРИТИЧЕСКАЯ ОШИБКА: Сервер {self.host} недоступен. Проверьте порт {self.port} или настройки файрвола (UFW)!")
            return False
        except Exception as e:
            logger.error(f"❌ [SSH] Непредвиденная ошибка при проверке связи: {e}")
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
            cmd = f"sudo sed -i 's/^#\\s*{login} :/{login} :/' {self.secrets_path} && sudo ipsec rereadsecrets"
        else:
            cmd = f"sudo sed -i 's/^{login} :/# {login} :/' {self.secrets_path} && sudo ipsec rereadsecrets"
            
        return await self._execute_ssh_cmd(cmd)

    async def delete_user(self, login: str) -> bool:
        """
        [УДАЛЕНИЕ]: Навсегда вырезает строки с пользователем из файла secrets.
        """
        cmd = f"sudo sed -i '/^{login} :/d' {self.secrets_path} && sudo sed -i '/^#\\s*{login} :/d' {self.secrets_path} && sudo ipsec rereadsecrets"
        return await self._execute_ssh_cmd(cmd)

strongswan_client = StrongSwanClient()


