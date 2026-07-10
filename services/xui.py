import logging
import json
import uuid
from typing import Optional, Dict, Any
import httpx
from bot.config import config

logger = logging.getLogger(__name__)

class XUIClient:
    def __init__(self):
        self.base_url = config.XUI_URL.rstrip('/') if config.XUI_URL else ""
        self.username = config.XUI_USER
        self.password = config.XUI_PASSWORD.get_secret_value() if config.XUI_PASSWORD else ""
        
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=10.0,
            follow_redirects=True,
            verify=False
        )

    async def login(self) -> bool:
        if not config.ENABLE_XUI or not self.base_url:
            logger.warning("Интеграция с 3x-ui отключена или не настроена.")
            return False

        url = "/login"
        data = {"username": self.username, "password": self.password}
        
        try:
            response = await self.client.post(url, data=data)
            if response.status_code != 200:
                return False
            resp_json = response.json()
            return resp_json.get("success") is True
        except Exception as e:
            logger.error(f"Исключение при логине в 3x-ui: {e}")
            return False

    async def _request(self, method: str, path: str, **kwargs) -> Optional[Dict[str, Any]]:
        url = path if path.startswith('/') else f"/{path}"
        try:
            response = await self.client.request(method, url, **kwargs)
            if response.status_code in [401, 302]:
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

    # --- НОВЫЕ МЕТОДЫ УПРАВЛЕНИЯ КЛИЕНТАМИ ---

    async def add_client(self, inbound_id: int, email: str, limit_ip: int = 2) -> Optional[str]:
        """
        Добавляет нового пользователя на указанный inbound (порт/протокол).
        Возвращает сгенерированный client_uuid (id) в случае успеха.
        """
        path = "/panel/api/inbounds/addClient"
        client_id = str(uuid.uuid4())  # Генерируем уникальный UUID для Xray/Trojan
        
        # Настройки клиента в соответствии с новой схемой БД 3x-ui
        client_settings = {
            "id": client_id,
            "alterId": 0,
            "email": email,
            "totalGB": 0,         # 0 — безлимитный трафик (контролируем через подписку бота)
            "expiryTime": 0,      # 0 — время контролируется ботом на уровне подписок
            "enable": True,
            "tgId": "",
            "subId": "",
            "limitIp": limit_ip,
            "flow": ""            # Для VLESS Reality панель сама применит flow, если он нужен
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
        """Удаляет клиента с инбаунда по его UUID/Email"""
        # В актуальных версиях удаление происходит через отправку UUID в пути или параметрах
        path = f"/panel/api/inbounds/delClient/{client_uuid}"
        # Для обратной совместимости некоторых версий MHSanaei также работает передача через ID инбаунда
        payload = {"id": inbound_id, "clientUUID": client_uuid}
        
        response = await self._request("POST", path, json=payload)
        if response and response.get("success") is True:
            return True
        
        # Альтернативный эндпоинт, если структура путей отличается в кастомных билдах
        alt_path = f"/panel/api/inbounds/{inbound_id}/delClient/{client_uuid}"
        response = await self._request("POST", alt_path)
        return response and response.get("success") is True

    async def set_client_status(self, inbound_id: int, client_uuid: str, enable: bool) -> bool:
        """Включает или выключает (деактивирует) ключ пользователя в панели"""
        path = f"/panel/api/inbounds/updateClient/{client_uuid}"
        
        client_settings = {
            "id": client_uuid,
            "enable": enable
        }
        
        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client_settings]})
        }
        
        response = await self._request("POST", path, json=payload)
        return response and response.get("success") is True

    async def get_inbound_info(self, inbound_id: int) -> Optional[Dict[str, Any]]:
        """Получает полную информацию об инбаунде (порт, протокол, стрим-настройки для генерации ссылок)"""
        path = f"/panel/api/inbounds/get/{inbound_id}"
        response = await self._request("GET", path)
        if response and response.get("success") is True:
            return response.get("obj")
        return None

    async def get_inbounds(self) -> Optional[list]:
        """Получает список всех входящих подключений (inbounds) из панели"""
        path = "/panel/api/inbounds/list"
        response = await self._request("GET", path)
        if response and response.get("success") is True:
            return response.get("obj", [])
        return None


    async def close(self):
        await self.client.aclose()

xui_client = XUIClient()
