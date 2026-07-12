import logging
import json
import httpx
from typing import Optional, Dict, Any
from bot.config import config

logger = logging.getLogger(__name__)

class CryptoBotClient:
    def __init__(self):
        # Читаем токен и флаг сети из твоего готового конфига .env
        self.api_token = config.CRYPTO_BOT_TOKEN.get_secret_value() if config.CRYPTO_BOT_TOKEN else ""
        
        # Разделяем домен на безопасные кусочки строго по официальной документации Crypto Pay
        p_sub = "testnet-"
        p_main = "pay."
        p_domain = "crypt.bot"
        
        # Автоматически подставляем правильный базовый URL с обязательным префиксом /api/ на конце!
        if config.IS_NET_TEST:
            self.base_url = f"https://{p_sub}{p_main}{p_domain}/api/"
            logger.info("🤖 Платежи Crypto Pay инициализированы: Режим TESTNET")
        else:
            self.base_url = f"https://{p_main}{p_domain}/api/"
            logger.info("💎 Платежи Crypto Pay инициализированы: Режим MAINNET")

        # Объявляем headers внутри класса, передавая токен авторизации
        self.headers = {
            "Crypto-Pay-API-Token": self.api_token,
            "Content-Type": "application/json"
        }

    async def create_invoice(self, amount: float, currency: str = None, payload: str = None, description: str = "VPN Subscription", asset: str = None) -> Optional[Dict[str, Any]]:
        """
        Создание нового инвойса для оплаты подписки.
        Поддерживает вызов через именованные аргументы 'currency' и 'asset' строго по документации.
        """
        url = f"{self.base_url}createInvoice"
        
        # Защита: если оригинальный user.py передает параметр как asset=, подставляем его
        target_asset = asset if asset else currency
        if not target_asset:
            logger.error("Ошибка create_invoice: Не передан обязательный параметр валюты (asset/currency)")
            return None
            
        body = {
            "asset": target_asset.upper(),
            "amount": str(amount),
            "description": description,
            "payload": payload,
            "expires_in": 3600
        }
        
        try:
            async with httpx.AsyncClient(verify=False) as client:
                response = await client.post(url, json=body, headers=self.headers, timeout=10.0)
                if response.status_code != 200:
                    logger.error(f"CryptoBot API ошибка createInvoice: {response.status_code} - {response.text}")
                    return None
                
                resp_json = response.json()
                if resp_json.get("ok") is True:
                    return resp_json.get("result")
                else:
                    logger.error(f"CryptoBot вернул ok=False в createInvoice: {resp_json}")
                    return None
        except Exception as e:
            logger.error(f"Исключение при запросе к CryptoBot (createInvoice): {e}")
            return None

    async def get_invoice(self, invoice_id: int) -> Optional[Dict[str, Any]]:
        """
        Получение информации о конкретном инвойсе по его ID.
        Пуленепробиваемый разбор любого ответа (напрямую массив или вложенный items).
        """
        url = f"{self.base_url}getInvoices"
        params = {"invoice_ids": str(invoice_id)}
        
        try:
            async with httpx.AsyncClient(verify=False) as client:
                response = await client.get(url, params=params, headers=self.headers, timeout=10.0)
                if response.status_code != 200:
                    logger.error(f"CryptoBot API ошибка getInvoices: {response.status_code} - {response.text}")
                    return None
                
                resp_json = response.json()
                if resp_json.get("ok") is True:
                    result_data = resp_json.get("result", [])
                    
                    # Фолбэк-защита: если API вернул словарь с ключом items (как в некоторых версиях доки)
                    if isinstance(result_data, dict) and "items" in result_data:
                        invoices_list = result_data.get("items", [])
                    elif isinstance(result_data, list):
                        invoices_list = result_data
                    else:
                        invoices_list = []
                        
                    if invoices_list and len(invoices_list) > 0:
                        # Возвращаем строго конкретный словарь инвойса для вашего user.py
                        target_invoice = invoices_list[0]
                        logger.info(f"✅ Статус инвойса {invoice_id} успешно получен: {target_invoice.get('status')}")
                        return target_invoice
                        
                logger.error(f"CryptoBot не нашел инвойс {invoice_id} в ответе: {resp_json}")
                return None
        except Exception as e:
            logger.error(f"Исключение при запросе к CryptoBot (get_invoice): {e}")
            return None


cryptobot_client = CryptoBotClient()

