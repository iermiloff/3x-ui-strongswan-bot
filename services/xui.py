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
        url_str = config.XUI_URL if config.XUI_URL else ""
        if url_str and not url_str.endswith('/'):
            url_str += '/'
        self.full_url = url_str
        
        # Теперь здесь хранится ваш API Токен из панели
        self.api_token = config.XUI_PASSWORD.get_secret_value() if config.XUI_PASSWORD else ""
        
        # Настраиваем авторизацию через Bearer-токен строго по спецификации OpenAPI
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_token}"
        }
        
        self.client = httpx.AsyncClient(
            base_url=self.full_url,
            timeout=10.0,
            follow_redirects=True,
            headers=headers,
            verify=False
        )

    async def login(self) -> bool:
        """Метод-заглушка. При Bearer-авторизации логин не требуется, токен активен всегда"""
        return True

    async def _request(self, method: str, path: str, **kwargs) -> Optional[Dict[str, Any]]:
        url = path.lstrip('/')
        try:
            response = await self.client.request(method, url, **kwargs)
            if response.status_code != 200:
                logger.error(f"Ошибка API запроса к {url}. Статус HTTP: {response.status_code}. Проверьте токен в .env!")
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

