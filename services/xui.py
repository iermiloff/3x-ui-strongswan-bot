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
        # Базовый URL со всеми путями (например, https://ip:port/WgijWp3l2YbP7Fc6Dc/)
        self.full_url = config.XUI_URL.rstrip('/') + '/' if config.XUI_URL else ""
        self.username = config.XUI_USER
        self.password = config.XUI_PASSWORD.get_secret_value() if config.XUI_PASSWORD else ""
        
        # Выделяем чистый корень (https://ip:port) специально для эндпоинта /login
        parsed = urllib.parse.urlparse(self.full_url)
        self.root_url = f"{parsed.scheme}://{parsed.netloc}" if self.full_url else ""
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        
        # Основной клиент работает с полным URL (для инбаундов и клиентов)
        self.client = httpx.AsyncClient(
            base_url=self.full_url,
            timeout=10.0,
            follow_redirects=True,
            headers=headers,
            verify=False
        )

    async def login(self) -> bool:
        """Авторизация в панели 3x-ui строго через корневой URL без кастомного пути"""
        if not config.ENABLE_XUI or not self.root_url:
            logger.warning("Интеграция с 3x-ui отключена или не настроена.")
            return False

        # Формируем запрос строго на https://ip:port/login
        login_url = f"{self.root_url}/login"
        payload = {
            "username": self.username,
            "password": self.password
        }
        
        try:
            # Пробуем отправить как Form Data (Стандарт для MHSanaei)
            response = await self.client.post(login_url, data=payload)
            
            # Если панель ожидает JSON-тело
            if response.status_code in [403, 405]:
                response = await self.client.post(login_url, json=payload)
            
            if response.status_code != 200:
                logger.error(f"Ошибка авторизации 3x-ui. Статус HTTP: {response.status_code}")
                return False
                
            resp_json = response.json()
            if resp_json.get("success") is True:
                logger.info("Успешная авторизация в панели 3x-ui!")
                return True
            else:
                logger.error(f"Панель вернула ошибку авторизации: {resp_json.get('msg')}")
                return False
                
        except Exception as e:
            logger.error(f"Исключение при попытке авторизации в 3x-ui: {e}")
            return False

    async def _request(self, method: str, path: str, **kwargs) -> Optional[Dict[str, Any]]:
        # Обрезаем ведущий слэш, так как httpx корректно объединяет base_url (заканчивающийся на /) и относительный путь
        url = path.lstrip('/')
        try:
            response = await self.client.request(method, url, **kwargs)
            if response.status_code in [401, 403]:
                if await self.login():
                    response = await self.client.request(method, url, **kwargs)
                else:
                    return None
            if response.status_code != 200:
                return None
            return response.json()
        except Exception as e:
            logger.error(f"Ошибка API запроса к {url}: {e}")
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

