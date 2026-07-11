import logging
import json
import io
import urllib.parse
import qrcode
import base64
from aiogram.types import BufferedInputFile

logger = logging.getLogger(__name__)

def generate_xui_link(target_inbound: dict, client_uuid: str, email: str, client_info: dict = None) -> str | None:
    """
    Каноничная сборка VPN-ссылок под MHSanaei 3.4.2 с индивидуальной маскировкой клиента.
    """
    try:
        protocol = target_inbound.get("protocol", "").lower()
        port = target_inbound.get("port")
        remark = target_inbound.get("remark", "VPN")
        
        from bot.config import config
        parsed_panel = urllib.parse.urlparse(config.XUI_URL)
        server_host = parsed_panel.hostname

        stream_settings = target_inbound.get("streamSettings", {})
        if isinstance(stream_settings, str):
            try: stream_settings = json.loads(stream_settings)
            except Exception: stream_settings = {}

        security = stream_settings.get("security", "none")
        network = stream_settings.get("network", "tcp")
        
        query_params = {}
        
        if network == "grpc":
            query_params["type"] = "grpc"
            grpc_settings = stream_settings.get("grpcSettings", {})
            if isinstance(grpc_settings, str):
                try: grpc_settings = json.loads(grpc_settings)
                except Exception: grpc_settings = {}
            query_params["serviceName"] = grpc_settings.get("serviceName", "UpdateServiceApis")
        else:
            query_params["type"] = network

        if security == "reality":
            query_params["security"] = "reality"
            
            reality_settings = stream_settings.get("realitySettings", {})
            if isinstance(reality_settings, str):
                try: reality_settings = json.loads(reality_settings)
                except Exception: reality_settings = {}
            
            inner_settings = reality_settings.get("settings", {})
            if isinstance(inner_settings, str):
                try: inner_settings = json.loads(inner_settings)
                except Exception: inner_settings = {}
            
            query_params["pbk"] = inner_settings.get("publicKey", "")
            query_params["fp"] = inner_settings.get("fingerprint", "qq")

            # ЖЕЛЕЗНО: Берем индивидуальный sid созданного клиента, если он пришел из API!
            if client_info and client_info.get("sid"):
                query_params["sid"] = client_info["sid"]
            else:
                short_ids = reality_settings.get("shortIds", [])
                query_params["sid"] = short_ids[0] if isinstance(short_ids, list) and short_ids else (short_ids if isinstance(short_ids, str) else "")
            
            # Извлекаем первый SNI
            server_names = reality_settings.get("serverNames", ["www.google.com"])
            query_params["sni"] = server_names[0] if isinstance(server_names, list) and server_names else (server_names if isinstance(server_names, str) else "www.google.com")
            
            # ЖЕЛЕЗНО: Берем индивидуальный spx созданного клиента!
            if client_info and client_info.get("spx"):
                query_params["spx"] = client_info["spx"]
            else:
                query_params["spx"] = inner_settings.get("spiderX", "/")
                
            query_params["authority"] = ""
            
        elif security == "tls":
            query_params["security"] = "tls"
            tls_settings = stream_settings.get("tlsSettings", {})
            if isinstance(tls_settings, str):
                try: tls_settings = json.loads(tls_settings)
                except Exception: tls_settings = {}
            query_params["sni"] = tls_settings.get("serverName", server_host)

        if protocol == "vless" and network == "tcp" and security == "reality":
            query_params["flow"] = "xtls-rprx-vision"

        query_string = urllib.parse.urlencode(query_params)
        safe_remark = urllib.parse.quote(f"{remark}-{email}")

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

