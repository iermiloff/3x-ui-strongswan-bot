import logging
from typing import Optional, Dict, Any
import httpx
from bot.config import config

logger = logging.getLogger(__name__)

class XUIClient:
    def __init__(self):
        # Базовый URL панели из конфига (например, http://ip:port)
        self.base_url = config.XUI_URL.rstrip('/')
        self.username = config.XUI_USER
        # Извлекаем пароль из SecretStr
        self.password = config.XUI_PASSWORD.get_secret_value() if config.XUI_PASSWORD else ""
        
        # Асинхронный клиент, который будет автоматически хранить куки сессии
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=10.0,
            follow_redirects=True
        )

    async def login(self) -> bool:
        """
        Авторизация в панели 3x-ui.
        В новых версиях используется POST на /login с параметрами username и password.
        """
        if not config.ENABLE_XUI:
            logger.warning("Интеграция с 3x-ui отключена в конфигурации.")
            return False

        url = "/login"
        data = {
            "username": self.username,
            "password": self.password
        }
        
        try:
            response = await self.client.post(url, data=data)
            
            # Проверяем успешность HTTP-статуса
            if response.status_code != 200:
                logger.error(f"Ошибка авторизации 3x-ui. Статус: {response.status_code}")
                return False
                
            # Проверяем JSON-ответ панели
            resp_json = response.json()
            if resp_json.get("success") is True:
                logger.info("Успешная авторизация в панели 3x-ui.")
                return True
            else:
                logger.error(f"Панель вернула ошибку авторизации: {resp_json.get('msg')}")
                return False
                
        except Exception as e:
            logger.error(f"Исключение при попытке авторизации в 3x-ui: {e}")
            return False

    async def _request(self, method: str, path: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Внутренний метод для выполнения запросов к API с автоматическим релогином
        в случае протухания сессионной куки.
        """
        url = path if path.startswith('/') else f"/{path}"
        
        try:
            response = await self.client.request(method, url, **kwargs)
            
            # Если панель возвращает 401 или перенаправляет на логин — пробуем переавторизоваться
            if response.status_code in:
                logger.info("Сессия 3x-ui устарела. Выполняю повторный вход...")
                if await self.login():
                    # Повторяем запрос после успешного релогина
                    response = await self.client.request(method, url, **kwargs)
                else:
                    return None

            if response.status_code != 200:
                logger.error(f"API запрос {url} завершился со статусом {response.status_code}")
                return None

            return response.json()
            
        except Exception as e:
            logger.error(f"Ошибка при выполнении API запроса к {url}: {e}")
            return None

    async def close(self):
        """Закрытие HTTP-клиента при остановке бота"""
        await self.client.aclose()

# Экспортируем готовый синглтон клиента
xui_client = XUIClient()
