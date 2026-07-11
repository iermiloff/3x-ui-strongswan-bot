import logging
from typing import Optional, Dict, Any
import httpx
from bot.config import config

logger = logging.getLogger(__name__)

class CryptoBotClient:
    def __init__(self):
        # Читаем токен и флаг сети из твоего готового конфига .env
        self.api_token = config.CRYPTO_BOT_TOKEN.get_secret_value() if config.CRYPTO_BOT_TOKEN else ""
        
        # Защищенная склейка доменов кусочками, чтобы парсер ничего не вырезал
        p_sub = "testnet-"
        p_main = "pay."
        p_domain = "cryptobot.in"
        
        # СТРОГО РАЗНЫЕ АДРЕСА ДЛЯ ТЕСТА И ПРОДА
        if config.IS_NET_TEST:
            self.base_url = f"https://{p_sub}{p_main}{p_domain}/"
            logger.info("🤖 Платежи Crypto Pay запущены в режиме TESTNET")
        else:
            self.base_url = f"https://{p_main}{p_domain}/"
            logger.info("💎 Платежи Crypto Pay запущены в режиме MAINNET (PRODUCTION)")


    async def _request(self, method: str, endpoint: str, json_data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Внутренний метод для выполнения асинхронных запросов к CryptoBot API"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.request(method, url, headers=self.headers, json=json_data)
                
                if response.status_code != 200:
                    logger.error(f"CryptoBot API ошибка {endpoint}: {response.status_code} - {response.text}")
                    return None
                    
                resp_json = response.json()
                if resp_json.get("ok") is True:
                    return resp_json.get("result")
                else:
                    logger.error(f"CryptoBot вернул ошибку в теле ответа: {resp_json}")
                    return None
        except Exception as e:
            logger.error(f"Исключение при запросе к CryptoBot ({endpoint}): {e}")
            return None

    async def create_invoice(
        self, 
        amount: float, 
        asset: str, 
        description: str, 
        payload: str
    ) -> Optional[Dict[str, Any]]:
        """
        Создает инвойс на оплату.
        :param amount: Сумма платежа (например, 5.00)
        :param asset: Криптовалюта (USDT, TON, BTC, ETH)
        :param description: Описание платежа для пользователя
        :param payload: Скрытые данные (например, "user_id:plan_type"), которые вернутся после оплаты
        """
        endpoint = "createInvoice"
        data = {
            "asset": asset,
            "amount": str(amount),
            "description": description,
            "payload": payload,
            # Кнопка возврата в бота после успешной оплаты
            "allow_comments": False,
            "allow_anonymous": False
        }
        
        return await self._request("POST", endpoint, json_data=data)

    async def get_invoice(self, invoice_id: int) -> Optional[Dict[str, Any]]:
        """Проверяет статус конкретного инвойса по его ID (полезно для лонг-поллинга)"""
        endpoint = "getInvoices"
        data = {"invoice_ids": str(invoice_id)}
        
        result = await self._request("POST", endpoint, json_data=data)
        if result and result.get("items"):
            return result["items"][0]  # Возвращаем информацию о первом найденном инвойсе
        return None

# Экспортируем готовый экземпляр
cryptobot_client = CryptoBotClient()
