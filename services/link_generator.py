import logging
import json
import io
import urllib.parse
import qrcode
from aiogram.types import BufferedInputFile

logger = logging.getLogger(__name__)

def generate_xui_link(target_inbound: dict, client_uuid: str, email: str) -> str | None:
    """
    Каноничная сборка VPN-ссылок под MHSanaei 3.4.2 (VLESS Reality / Trojan / Shadowsocks).
    Безопасно переваривает и словари, и строки в ответах API.
    """
    try:
        protocol = target_inbound.get("protocol", "").lower()
        port = target_inbound.get("port")
        remark = target_inbound.get("remark", "VPN")
        
        # 1. Извлекаем домен/IP сервера из настроек или используем глобальный хост
        # Парсим URL панели, чтобы вытащить чистый IP/домен для ссылки клиента
        from bot.config import config
        parsed_panel = urllib.parse.urlparse(config.XUI_URL)
        server_host = parsed_panel.hostname

        # 2. Адаптивно извлекаем streamSettings (работаем и со строкой, и со словарем)
        stream_settings = target_inbound.get("streamSettings", {})
        if isinstance(stream_settings, str):
            try:
                stream_settings = json.loads(stream_settings)
            except Exception:
                stream_settings = {}

        # 3. Сборка ссылки в зависимости от протокола
        if protocol == "vless":
            security = stream_settings.get("security", "none")
            network = stream_settings.get("network", "tcp")
            
            # Базовая структура VLESS
            link = f"vless://{client_uuid}@{server_host}:{port}?security={security}&type={network}"
            
            # Если включен нативный VLESS Reality (стандарт MHSanaei 3.x)
            if security == "reality":
                reality_settings = stream_settings.get("realitySettings", {})
                
                # Собираем параметры Reality (публичный ключ, SNI, Short ID и Flow)
                public_key = reality_settings.get("publicKey", "")
                short_id = ""
                short_ids = reality_settings.get("shortIds", [])
                if short_ids:
                    short_id = short_ids[0] # Берем первый доступный ID
                    
                server_names = reality_settings.get("serverNames", ["google.com"])
                sni = server_names[0] if server_names else "google.com"
                
                # Дописываем параметры в query-строку
                link += f"&pbk={public_key}&sni={sni}&sid={short_id}"
                
                # Выставляем XTLS Vision flow, если сеть поддерживает TCP
                if network == "tcp":
                    link += "&flow=xtls-rprx-vision"
                    
            # Добавляем имя (Remark) в конец ссылки в формате URL-safe
            safe_remark = urllib.parse.quote(f"{remark}-{email}")
            link += f"#{safe_remark}"
            return link

        elif protocol == "trojan":
            # Trojan ссылки имеют формат trojan://password@host:port
            safe_remark = urllib.parse.quote(f"{remark}-{email}")
            return f"trojan://{client_uuid}@{server_host}:{port}?type=tcp#{safe_remark}"

        elif protocol == "shadowsocks":
            # Извлекаем шифр (метод) Shadowsocks из настроек инбаунда
            inbound_settings = target_inbound.get("settings", {})
            if isinstance(inbound_settings, str):
                try:
                    inbound_settings = json.loads(inbound_settings)
                except Exception:
                    inbound_settings = {}
            
            method = inbound_settings.get("method", "aes-256-gcm")
            
            # Shadowsocks требует кодирование метода и пароля в Base64 для URI-стандарта
            import base64
            user_pass = f"{method}:{client_uuid}"
            encoded_user_pass = base64.b64encode(user_pass.encode('utf-8')).decode('utf-8')
            
            safe_remark = urllib.parse.quote(f"{remark}-{email}")
            return f"ss://{encoded_user_pass}@{server_host}:{port}#{safe_remark}"

        else:
            logger.warning(f"Протокол {protocol} пока не поддерживается генератором ссылок.")
            return None

    except Exception as e:
        logger.error(f"Ошибка при сборке ссылки подключения: {e}")
        return None


def create_qr_code_file(config_link: str, filename: str = "vpn_config.png") -> BufferedInputFile:
    """
    Генерация QR-кода строго в оперативной памяти (ОЗУ) сервера без нагрузки на SSD.
    Возвращает валидный BufferedInputFile для моментальной отправки в aiogram.
    """
    try:
        # Настраиваем параметры QR
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(config_link)
        qr.make(fit=True)

        # Рендерим картинку в байтовый буфер BytesIO
        img = qr.make_image(fill_color="black", back_color="white")
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        bio.seek(0) # Смещаем указатель в начало буфера для чтения

        # Упаковываем байты в формат aiogram 3.x
        return BufferedInputFile(bio.read(), filename=filename)
    except Exception as e:
        logger.error(f"Критическая ошибка генерации QR-кода в ОЗУ: {e}")
        raise e
