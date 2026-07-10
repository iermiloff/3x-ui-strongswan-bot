import logging
import json
import io
import urllib.parse
import qrcode
from aiogram.types import BufferedInputFile

logger = logging.getLogger(__name__)

def generate_xui_link(target_inbound: dict, client_uuid: str, email: str) -> str | None:
    """
    Каноничная сборка VPN-ссылок под MHSanaei 3.4.2.
    Полноценно поддерживает Reality, gRPC, TCP и XTLS для VLESS и Trojan протоколов.
    """
    try:
        protocol = target_inbound.get("protocol", "").lower()
        port = target_inbound.get("port")
        remark = target_inbound.get("remark", "VPN")
        
        from bot.config import config
        parsed_panel = urllib.parse.urlparse(config.XUI_URL)
        server_host = parsed_panel.hostname

        # Извлекаем streamSettings
        stream_settings = target_inbound.get("streamSettings", {})
        if isinstance(stream_settings, str):
            try:
                stream_settings = json.loads(stream_settings)
            except Exception:
                stream_settings = {}

        security = stream_settings.get("security", "none")
        network = stream_settings.get("network", "tcp")
        
        # Общие query-параметры для транспорта
        query_params = {}
        
        # Настройка транспорта (gRPC / TCP / WS)
        if network == "grpc":
            query_params["type"] = "grpc"
            grpc_settings = stream_settings.get("grpcSettings", {})
            service_name = grpc_settings.get("serviceName", "")
            if service_name:
                query_params["serviceName"] = service_name
        else:
            query_params["type"] = network

        # Настройка маскировки Reality / TLS
        if security == "reality":
            query_params["security"] = "reality"
            reality_settings = stream_settings.get("realitySettings", {})
            
            query_params["pbk"] = reality_settings.get("publicKey", "")
            query_params["fp"] = reality_settings.get("fingerprint", "chrome")
            
            # Извлекаем Short ID
            short_ids = reality_settings.get("shortIds", [])
            query_params["sid"] = short_ids if short_ids else ""
            
            # Извлекаем SNI
            server_names = reality_settings.get("serverNames", ["google.com"])
            query_params["sni"] = server_names if server_names else "google.com"
            
            # Дополнительные специфические параметры Reality (spx и authority)
            if reality_settings.get("spiderX"):
                query_params["spx"] = reality_settings.get("spiderX")
            query_params["authority"] = ""
        elif security == "tls":
            query_params["security"] = "tls"
            tls_settings = stream_settings.get("tlsSettings", {})
            query_params["sni"] = tls_settings.get("serverName", server_host)

        # Выставляем XTLS Vision flow только для VLESS на TCP
        if protocol == "vless" and network == "tcp" and security == "reality":
            query_params["flow"] = "xtls-rprx-vision"

        # Формируем query-строку
        query_string = urllib.parse.urlencode(query_params)
        safe_remark = urllib.parse.quote(f"{remark}-{email}")

        # Сборка финального URI
        if protocol == "vless":
            return f"vless://{client_uuid}@{server_host}:{port}?{query_string}#{safe_remark}"
            
        elif protocol == "trojan":
            return f"trojan://{client_uuid}@{server_host}:{port}?{query_string}#{safe_remark}"

        elif protocol == "shadowsocks":
            inbound_settings = target_inbound.get("settings", {})
            if isinstance(inbound_settings, str):
                try: inbound_settings = json.loads(inbound_settings)
                except Exception: inbound_settings = {}
            method = inbound_settings.get("method", "aes-256-gcm")
            
            import base64
            user_pass = f"{method}:{client_uuid}"
            encoded_user_pass = base64.b64encode(user_pass.encode('utf-8')).decode('utf-8')
            return f"ss://{encoded_user_pass}@{server_host}:{port}#{safe_remark}"

        return None
    except Exception as e:
        logger.error(f"Ошибка при сборке ссылки подключения: {e}")
        return None

def create_qr_code_file(config_link: str, filename: str = "vpn_config.png") -> BufferedInputFile:
    try:
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
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
