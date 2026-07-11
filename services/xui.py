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
        
        self.api_token = config.XUI_PASSWORD.get_secret_value() if config.XUI_PASSWORD else ""
        
        # Переменная в ОЗУ для хранения публичного ключа Reality
        self.reality_public_key = ""
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        
        self.client = httpx.AsyncClient(
            base_url=self.full_url,
            timeout=10.0,
            follow_redirects=True,
            headers=headers,
            verify=False
        )

    async def login(self) -> bool:
        """
        При первичном вызове (в main.py) запрашиваем список портов 
        и разово кешируем publicKey из Reality-настроек панели в ОЗУ.
        """
        try:
            inbounds = await self.get_inbounds()
            if inbounds:
                for ib in inbounds:
                    # Ищем инбаунд, где включен reality
                    stream_settings = ib.get("streamSettings", {})
                    if isinstance(stream_settings, str):
                        import json
                        try: stream_settings = json.loads(stream_settings)
                        except: stream_settings = {}
                    
                    if stream_settings.get("security") == "reality":
                        reality_settings = stream_settings.get("realitySettings", {})
                        if isinstance(reality_settings, str):
                            try: reality_settings = json.loads(reality_settings)
                            except: reality_settings = {}
                        
                        pk = reality_settings.get("publicKey", "")
                        if pk:
                            self.reality_public_key = pk
                            logger.info(f"✅ Публичный ключ Reality успешно кеширован в ОЗУ: {pk[:10]}...")
                            break
            return True
        except Exception as e:
            logger.error(f"Не удалось закешировать publicKey при старте: {e}")
            return True

    async def _request(self, method: str, path: str, **kwargs) -> Optional[Dict[str, Any]]:
        url = path.lstrip('/')
        try:
            response = await self.client.request(method, url, **kwargs)
            if response.status_code != 200:
                logger.error(f"Ошибка API запроса к {url}. Статус HTTP: {response.status_code}.")
                return None
            return response.json()
        except Exception as e:
            logger.error(f"Ошибка API запроса к {url}: {e}")
            return None

    async def add_client(self, inbound_id: int, email: str, limit_ip: int = 2) -> Optional[dict]:
        """Добавление клиента с поддержкой полей ID и Password для всех протоколов"""
        path = "panel/api/clients/add"
        client_uuid = uuid.uuid4().hex
        
        payload = {
            "client": {
                "email": email,
                "totalGB": 0,
                "expiryTime": 0,
                "tgId": 0,
                "limitIp": limit_ip,
                "enable": True,
                "id": client_uuid,       # Для VLESS
                "password": client_uuid  # ИСПРАВЛЕНО: Для Trojan строго передаем 32-значный hex сюда!
            },
            "inboundIds": [inbound_id]
        }
        
        response = await self._request("POST", path, json=payload)
        if response and response.get("success") is True:
            return {
                "uuid": client_uuid,
                "sid": "",
                "spx": ""
            }
        return None



    async def delete_client(self, inbound_id: int, client_uuid: str) -> bool:
        """В новом API удаление идет по email. Мы используем UUID как уникальный email"""
        path = f"panel/api/clients/del/{client_uuid}"
        response = await self._request("POST", path, params={"keepTraffic": 0})
        return response and response.get("success") is True

    async def set_client_status(self, inbound_id: int, client_uuid: str, enable: bool) -> bool:
        """В новом API блокировка идет через bulk-эндпоинты по списку email"""
        path = "panel/api/clients/bulkEnable" if enable else "panel/api/clients/bulkDisable"
        payload = {"emails": [client_uuid]}
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

