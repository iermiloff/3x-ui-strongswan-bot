import json
import urllib.parse
from typing import Optional, Dict, Any
from bot.config import config

def generate_xui_link(inbound: Dict[str, Any], client_uuid: str, email: str) -> Optional[str]:
    """
    Динамически собирает валидную ссылку подключения (VLESS, Trojan, Shadowsocks)
    на основе реальных настроек инбаунда из 3x-ui панели.
    """
    try:
        protocol = inbound.get("protocol", "").lower()
        port = inbound.get("port")
        
        # Достаем домен или IP сервера из URL панели
        parsed_url = urllib.parse.urlparse(config.XUI_URL)
        host = parsed_url.hostname

        # Парсим внутренние настройки инбаунда
        stream_settings_str = inbound.get("streamSettings", "{}")
        stream_settings = json.loads(stream_settings_str)
        
        network = stream_settings.get("network", "tcp")
        security = stream_settings.get("security", "none")
        
        # Базовые параметры запроса (query-параметры)
        params = {
            "type": network
        }
        
        # Обработка Reality / TLS настройки
        if security == "reality":
            reality_settings = stream_settings.get("realitySettings", {})
            params["security"] = "reality"
            
            # Извлекаем публичный ключ и Short ID из настроек панели
            if reality_settings.get("publicKey"):
                params["pbk"] = reality_settings["publicKey"]
            
            short_ids = reality_settings.get("shortIds", [])
            if short_ids:
                params["sid"] = short_ids[0]
                
            # Добавляем SNI (домен-маскировку) и Fingerprint
            server_names = reality_settings.get("serverNames", [])
            if server_names:
                params["sni"] = server_names[0]
                
            params["fp"] = reality_settings.get("fingerprint", "chrome")
            
            # Для VLESS Reality необходим flow xtls-rprx-vision
            if protocol == "vless":
                params["flow"] = "xtls-rprx-vision"
                
        elif security == "tls":
            tls_settings = stream_settings.get("tlsSettings", {})
            params["security"] = "tls"
            server_names = tls_settings.get("serverNames", [])
            if server_names:
                params["sni"] = server_names[0]

        # Обработка транспортов вроде gRPC или WebSocket
        if network == "grpc":
            grpc_settings = stream_settings.get("grpcSettings", {})
            params["serviceName"] = grpc_settings.get("serviceName", "")
        elif network == "ws":
            ws_settings = stream_settings.get("wsSettings", {})
            params["path"] = ws_settings.get("path", "/")
            headers = ws_settings.get("headers", {})
            if "Host" in headers:
                params["host"] = headers["Host"]

        # Формируем remark (название ключа в приложении)
        remark = f"VPN_{protocol.upper()}_{email.split('_')[0]}"
        encoded_remark = urllib.parse.quote(remark)
        
        # Собираем финальный URI
        query_string = urllib.parse.urlencode(params)
        
        # Для Shadowsocks и Trojan формат может слегка отличаться, но базовый стандарт Xray один:
        link = f"{protocol}://{client_uuid}@{host}:{port}?{query_string}#{encoded_remark}"
        return link

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Ошибка при сборке ссылки подключения: {e}")
        return None
