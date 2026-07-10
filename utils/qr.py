import io
import qrcode
from aiogram.types import BufferedInputFile

def create_qr_code_file(text: str, filename: str = "vpn_config.png") -> BufferedInputFile:
    """
    Генерирует QR-код из текста (ссылки конфигурации) в оперативной памяти 
    и возвращает объект BufferedInputFile для aiogram.
    """
    # Настройки отображения QR-кода
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(text)
    qr.make(fit=True)

    # Создаем изображение (черно-белое)
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Сохраняем картинку в байтовый буфер в памяти
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    # Возвращаем готовый файл для отправки через bot.send_photo
    return BufferedInputFile(img_byte_arr.getvalue(), filename=filename)
