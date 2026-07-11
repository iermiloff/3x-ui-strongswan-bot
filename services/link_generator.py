import logging
import json
import io
import urllib.parse
import qrcode
import base64
from aiogram.types import BufferedInputFile

logger = logging.getLogger(__name__)

def generate_xui_link(target_inbound: dict, client_uuid: str, email: str) -> str | None:
    """
    Каноничная сборка VPN-ссылок под MHSanaei 3.4.2.
    Полноценно поддерживает Reality, gRPC, TCP, TLS и XTLS для VLESS, Trojan и Shadowsocks.
    Автоматически извлекает строки из списков (Short IDs, Server Names), защищая от битых ссылок.
    """
    try:
        protocol = target_inbound.get("protocol", "").lower()
        port = target_inbound.get("port")
        remark = target_inbound.get("remark", "VPN")
        
        # Парсим URL панели из конфига, чтобы вытащить чистый IP или домен сервера для ссылки
        from bot.config import config
        parsed_panel = urllib.parse.urlparse(config.XUI_URL)
        server_host = parsed_panel.hostname

        # Безопасно извлекаем streamSettings (работаем и со строкой, и со словарем)
        stream_settings = target_inbound.get("streamSettings", {})
        if isinstance(stream_settings, str):
            try:
                stream_settings = json.loads(stream_settings)
            except Exception:
                stream_settings = {}

        security = stream_settings.get("security", "none")
        network = stream_settings.get("network", "tcp")
        
        # Словарь для формирования query-параметров подключения
        query_params = {}
        
        # 1. НАСТРОЙКА ТРАНСПОРТА (gRPC / TCP / WS / HTTP)
        if network == "grpc":
            query_params["type"] = "grpc"
            grpc_settings = stream_settings.get("grpcSettings", {})
            if isinstance(grpc_settings, str):
                try: grpc_settings = json.loads(grpc_settings)
                except Exception: grpc_settings = {}
                
            service_name = grpc_settings.get("serviceName", "")
            if service_name:
                query_params["serviceName"] = service_name
        else:
            query_params["type"] = network

        # 2. НАСТРОЙКА ЗАЩИТЫ И МАСКИРОВКИ (Reality / TLS / None)
        if security == "reality":
            query_params["security"] = "reality"
            reality_settings = stream_settings.get("realitySettings", {})
            if isinstance(reality_settings, str):
                try: reality_settings = json.loads(reality_settings)
                except Exception: reality_settings = {}
            
            api_pbk = reality_settings.get("publicKey", "")
            
            # ТОЧЕЧНОЕ РЕШЕНИЕ: Если ключ пустой, запрашиваем полный список на лету
            if not api_pbk:
                from bot.services.xui import xui_client
                # Вызываем асинхронный метод внутри синхронной функции генератора
                try:
                    import asyncio
                    inbounds_list = asyncio.run_coroutine_threadsafe(
                        xui_client.get_inbounds(), 
                        asyncio.get_event_loop()
                    ).result()
                except Exception:
                    # Фолбэк, если дефолтный луп занят (для aiogram 3)
                    try:
                        loop = asyncio.get_running_loop()
                        inbounds_list = loop.run_until_complete(xui_client.get_inbounds())
                    except Exception:
                        inbounds_list = None
                        
                if inbounds_list:
                    target_raw = next((ib for ib in inbounds_list if ib.get("id") == target_inbound.get("id")), None)
                    if target_raw:
                        raw_stream = target_raw.get("streamSettings", {})
                        if isinstance(raw_stream, str):
                            try: raw_stream = json.loads(raw_stream)
                            except: raw_stream = {}
                        raw_reality = raw_stream.get("realitySettings", {})
                        if isinstance(raw_reality, str):
                            try: raw_reality = json.loads(raw_reality)
                            except: raw_reality = {}
                        api_pbk = raw_reality.get("publicKey", "")

            query_params["pbk"] = api_pbk


            
            # ЗАЩИТА: Извлекаем строго первый Short ID, если пришел список (как в 3.4.2)
            short_ids = reality_settings.get("shortIds", [])
            if isinstance(short_ids, list) and short_ids:
                query_params["sid"] = str(short_ids[0])
            elif isinstance(short_ids, str):
                query_params["sid"] = short_ids
            else:
                query_params["sid"] = ""
            
            # ЗАЩИТА: Извлекаем строго первый домен маскировки (SNI), если пришел список
            server_names = reality_settings.get("serverNames", ["google.com"])
            if isinstance(server_names, list) and server_names:
                query_params["sni"] = str(server_names[0])
            elif isinstance(server_names, str):
                query_params["sni"] = server_names
            else:
                query_params["sni"] = "google.com"
            
            # Дополнительные специфические параметры Reality (spx)
            if reality_settings.get("spiderX"):
                query_params["spx"] = reality_settings.get("spiderX")
                
            query_params["authority"] = ""
            
        elif security == "tls":
            query_params["security"] = "tls"
            tls_settings = stream_settings.get("tlsSettings", {})
            if isinstance(tls_settings, str):
                try: tls_settings = json.loads(tls_settings)
                except Exception: tls_settings = {}
            query_params["sni"] = tls_settings.get("serverName", server_host)

        # 3. СПЕЦИФИКА КЛИЕНТСКИХ ФЛАГОВ (XTLS Vision Flow для VLESS на TCP)
        if protocol == "vless" and network == "tcp" and security == "reality":
            query_params["flow"] = "xtls-rprx-vision"

        # Формируем query-строку и имя конфигурации (Remark) в URL-safe формате
        query_string = urllib.parse.urlencode(query_params)
        safe_remark = urllib.parse.quote(f"{remark}-{email}")

        # 4. ФИНАЛЬНАЯ СБОРКА ССЫЛКИ ПО ПРОТОКОЛАМ
        if protocol == "vless":
            return f"vless://{client_uuid}@{server_host}:{port}?{query_string}#{safe_remark}"
            
        elif protocol == "trojan":
            return f"trojan://{client_uuid}@{server_host}:{port}?{query_string}#{safe_remark}"

        elif protocol == "shadowsocks":
            inbound_settings = target_inbound.get("settings", {})
            if isinstance(inbound_settings, str):
                try:
                    inbound_settings = json.loads(inbound_settings)
                except Exception:
                    inbound_settings = {}
            method = inbound_settings.get("method", "aes-256-gcm")
            
            # Shadowsocks требует кодирования связки 'метод:пароль' в Base64
            user_pass = f"{method}:{client_uuid}"
            encoded_user_pass = base64.b64encode(user_pass.encode('utf-8')).decode('utf-8')
            return f"ss://{encoded_user_pass}@{server_host}:{port}#{safe_remark}"

        logger.warning(f"Протокол {protocol} не поддерживается генератором ссылок.")
        return None
    except Exception as e:
        logger.error(f"Ошибка при сборке ссылки подключения: {e}")
        return None


def create_qr_code_file(config_link: str, filename: str = "vpn_config.png") -> BufferedInputFile:
    """Генерация QR-кода строго в оперативной памяти (ОЗУ) сервера без нагрузки на NVMe/SSD"""
    try:
        qr = qrcode.QRCode(
            version=1, 
            error_correction=qrcode.constants.ERROR_CORRECT_L, 
            box_size=10, 
            border=4
        )
        qr.add_data(config_link)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        bio.seek(0)
        return BufferedInputFile(bio.read(), filename=filename)
    except Exception as e:
        logger.error(f"Критическая ошибка генерации QR-кода: {e}")
        raise e

