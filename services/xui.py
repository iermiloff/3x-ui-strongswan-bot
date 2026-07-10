import logging
import json
import uuid
import urllib.parse
from typing import Optional, Dict, Any
import httpx
from bot.config import config

logger = logging.getLogger(__name__)

class XUIClient:
    def __init__(self):
        # Читаем адрес из .env (https://188.120.234.166:10569/WgijWp3l2YbP7Fc6Dc)
        raw_url = config.XUI_URL if config.XUI_URL else ""
        parsed = urllib.parse.urlparse(raw_url)
        
        # Выделяем ЧИСТЫЙ КОРЕНЬ сервера (https://188.120.234.166:10569) строго по OpenAPI
        self.root_url = f"{parsed.scheme}://{parsed.netloc}/" if raw_url else ""
        
        self.username = config.XUI_USER
        self.password = config.XUI_PASSWORD.get_secret_value() if config.XUI_PASSWORD else ""
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json"
        }
        
        # Клиент инициализируется на чистый корень IP:ПОРТ
        self.client = httpx.AsyncClient(
            base_url=self.root_url,
            timeout=10.0,
            follow_redirects=True,
            headers=headers,
            verify=False
        )

    async def login(self) -> bool:
        """Авторизация по каноничному пути OpenAPI с JSON-телом"""
        if not config.ENABLE_XUI or not self.root_url:
            logger.warning("Интеграция с 3x-ui отключена или не настроена.")
            return False

        # Запрос идет строго на https://ip:port/login
        login_path = "login"
        payload = {
            "username": self.username,
            "password": self.password,
            "twoFactorCode": "" # Пустая строка, если 2FA отключен в панели
        }
        
        try:
            # Отправляем СТРОГО json=payload (Content-Type: application/json)
            response = await self.client.post(login_path, json=payload)
            
            if response.status_code != 200:
                logger.error(f"Ошибка авторизации 3x-ui. Статус HTTP: {response.status_code}. Проверьте логин/пароль.")
                return False
                
            resp_json = response.json()
            if resp_json.get("success") is True:
                logger.info("✅ Успешная авторизация в панели 3x-ui по спецификации OpenAPI!")
                return True
            else:
                logger.error(f"Панель отклонила учетные данные: {resp_json.get('msg')}")
                return False
                
        except Exception as e:
            logger.error(f"Исключение при попытке авторизации в 3x-ui: {e}")
            return False

    async def _request(self, method: str, path: str, **kwargs) -> Optional[Dict[str, Any]]:
        # Все рабочие запросы автоматически дополняются вашим кастомным префиксом из .env
        raw_url = config.XUI_URL if config.XUI_URL else ""
        parsed = urllib.parse.urlparse(raw_url)
        base_path = parsed.path.strip("/")
        
        # Формируем правильный путь (например, WgijWp3l2YbP7Fc6Dc/panel/api/inbounds/list)
        full_path = f"{base_path}/{path.lstrip('/')}"
        
        try:
            response = await self.client.request(method, full_path, **kwargs)
            if response.status_code == 401 or response.status_code == 302:
                if await self.login():
                    response = await self.client.request(method, full_path, **kwargs)
                else:
                    return None
            if response.status_code != 200:
                return None
            return response.json()
        except Exception as e:
            logger.error(f"Ошибка API запроса к {full_path}: {e}")
            return None

    async def add_client(self, inbound_id: int, email: str, limit_ip: int = 2) -> Optional[str]:
        path = "panel/api/inbounds/addClient"
        client_id = str(uuid.uuid4())
        client_settings = {
            "id": client_id,
            "alterId": 0,
            "email": email,
            "totalGB": 0,
            "expiryTime": 0,
            "enable": True,
            "tgId": "",
            "subId": "",
            "limitIp": limit_ip,
            "flow": ""
        }
        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client_settings]})
        }
        response = await self._request("POST", path, json=payload)
        if response and response.get("success") is True:
            return client_id
        return None

    async def delete_client(self, inbound_id: int, client_uuid: str) -> bool:
        path = f"panel/api/inbounds/delClient/{client_uuid}"
        payload = {"id": inbound_id, "clientUUID": client_uuid}
        response = await self._request("POST", path, json=payload)
        return response and response.get("success") is True

    async def set_client_status(self, inbound_id: int, client_uuid: str, enable: bool) -> bool:
        path = f"panel/api/inbounds/updateClient/{client_uuid}"
        client_settings = {"id": client_uuid, "enable": enable}
        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client_settings]})
        }
        response = await self._request("POST", path, json=payload)
        return response and response.get("success") is True

    async def get_inbound_info(self, inbound_id: int) -> Optional[Dict[str, Any]]:
        path = f"panel/api/inbounds/get/{inbound_id}"
        response = await self._request("GET", path)
        if response and response.get("success") is True:
            return response.get("obj")
        return None

    async def get_inbounds(self) -> Optional[list]:
        path = "panel/api/inbounds/list"
        response = await self._request("GET", path)
        if response and response.get("success") is True:
            return response.get("obj", [])
        return None

    async def close(self):
        await self.client.aclose()

xui_client = XUIClient()


