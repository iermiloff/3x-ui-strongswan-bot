import logging
import json
import urllib.parse
from aiogram import Router, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.config import config
from bot.database.models import TariffInbound, SubscriptionType, User, Subscription
from bot.services.xui import xui_client

logger = logging.getLogger(__name__)
admin_router = Router()

# Строгий забор на уровне роутера — пускает только администраторов из .env
admin_router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
admin_router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

class AdminStates(StatesGroup):
    SELECT_PLAN = State()
    SELECT_INBOUND = State()

def get_admin_main_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="⚙️ Настройка инбаундов 3x-ui", callback_query_data="admin_setup_xui")],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_query_data="menu_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@admin_router.callback_query(F.data == "menu_stats")
async def cmd_admin_stats(callback: CallbackQuery, db_session: AsyncSession):
    await callback.answer()
    
    # Считаем финансовые и пользовательские метрики в БД
    res_users = await db_session.execute(select(User))
    total_users = len(res_users.scalars().all())
    
    res_subs = await db_session.execute(select(Subscription).where(Subscription.expires_at > datetime.utcnow()))
    active_subs = len(res_subs.scalars().all())
    
    stats_text = (
        f"📊 <b>Панель администратора Overlord VPN</b>\n\n"
        f"• Всего пользователей в БД: <code>{total_users}</code>\n"
        f"• Активных платных подписок: <code>{active_subs}</code>\n"
        f"• Токен авторизации 3x-ui: <code>Активен (Bearer Token)</code>\n\n"
        f"Управляйте распределением портов по тарифам через меню ниже:"
    )
    await callback.message.edit_text(text=stats_text, reply_markup=get_admin_main_keyboard())

@admin_router.callback_query(F.data == "admin_setup_xui")
async def admin_setup_xui(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    keyboard = [
        [InlineKeyboardButton(text="Базовый (BASE / Триал)", callback_query_data="admin_plan_base")],
        [InlineKeyboardButton(text="Премиум (PREMIUM)", callback_query_data="admin_plan_premium")],
        [InlineKeyboardButton(text="❌ Отмена", callback_query_data="menu_stats")]
    ]
    await callback.message.edit_text(
        text="👉 Выберите <b>Тарифный план</b>, для которого хотите настроить порты выдачи:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await state.set_state(AdminStates.SELECT_PLAN)

@admin_router.callback_query(F.data.startswith("admin_plan_"))
async def admin_select_inbound(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    await callback.answer()
    plan_str = callback.data.replace("admin_plan_", "").upper()
    selected_plan = SubscriptionType.BASE if plan_str == "BASE" else SubscriptionType.PREMIUM
    await state.update_data(selected_plan=selected_plan)
    
    inbounds = await xui_client.get_inbounds()
    if inbounds is None:
        await callback.message.edit_text("❌ Ошибка соединения с API 3x-ui.", reply_markup=get_admin_main_keyboard())
        await state.clear()
        return

    res_tariffs = await db_session.execute(select(TariffInbound))
    current_tariffs = {t.inbound_id: t for t in res_tariffs.scalars().all()}
    
    keyboard = []
    for ib in inbounds:
        ib_id = ib.get("id")
        port = ib.get("port")
        protocol = ib.get("protocol", "").upper()
        remark = ib.get("remark", "")
        
        status_tag = "⚪️"
        if ib_id in current_tariffs:
            status_tag = "🟢 [БАЗОВЫЙ]" if current_tariffs[ib_id].plan_type == SubscriptionType.BASE else "🔵 [PREMIUM]"
            
        btn_text = f"{status_tag} ID: {ib_id} | {protocol} ({port}) | {remark}"
        keyboard.append([InlineKeyboardButton(text=btn_text, callback_query_data=f"admin_toggle_ib_{ib_id}")])
        
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_query_data="admin_setup_xui")])
    await callback.message.edit_text(
        text=f"⚙️ <b>Инбаунды тарифа {selected_plan.value.upper()}</b>\n\nКликните для изменения статуса:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await state.set_state(AdminStates.SELECT_INBOUND)

@admin_router.callback_query(F.data.startswith("admin_toggle_ib_"))
async def admin_toggle_inbound_process(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    selected_inbound_id = int(callback.data.replace("admin_toggle_ib_", ""))
    data = await state.get_data()
    selected_plan = data.get("selected_plan")
    
    res = await db_session.execute(select(TariffInbound).where(TariffInbound.inbound_id == selected_inbound_id))
    existing_tariff = res.scalar_or_none()
    
    if existing_tariff:
        if existing_tariff.plan_type == selected_plan:
            await db_session.delete(existing_tariff)
            await db_session.commit()
            await callback.answer("ℹ️ Инбаунд успешно отключен от бота!", show_alert=True)
        else:
            existing_tariff.plan_type = selected_plan
            inbounds_list = await xui_client.get_inbounds()
            target_raw_inbound = next((ib for ib in inbounds_list if ib.get("id") == selected_inbound_id), None)
            if target_raw_inbound:
                existing_tariff.link_template = build_secure_template(target_raw_inbound)
            await db_session.commit()
            await callback.answer(f"🔄 Перенесено на тариф {selected_plan.value.upper()}!", show_alert=True)
    else:
        inbounds_list = await xui_client.get_inbounds()
        target_raw_inbound = next((ib for ib in inbounds_list if ib.get("id") == selected_inbound_id), None)
        if not target_raw_inbound:
            await callback.answer("❌ Ошибка: Инбаунд удален в панели 3x-ui!", show_alert=True)
            return
            
        link_template = build_secure_template(target_raw_inbound)
        new_tariff = TariffInbound(
            plan_type=selected_plan, inbound_id=selected_inbound_id,
            protocol_name=target_raw_inbound.get("protocol", "vless").upper(),
            remark=target_raw_inbound.get("remark", "VPN"), link_template=link_template
        )
        db_session.add(new_tariff)
        await db_session.commit()
        await callback.answer("✅ Инбаунд привязан, шаблон Reality-gRPC сохранен!", show_alert=True)
        
    callback.data = f"admin_plan_{selected_plan.value.lower()}"
    await admin_select_inbound(callback, state, db_session)

def build_secure_template(ib: dict) -> str:
    protocol = ib.get("protocol", "").lower()
    port = ib.get("port")
    remark = ib.get("remark", "VPN")
    server_host = urllib.parse.urlparse(config.XUI_URL).hostname
    
    stream_settings = ib.get("streamSettings", {})
    if isinstance(stream_settings, str):
        try: stream_settings = json.loads(stream_settings)
        except Exception: stream_settings = {}
        
    security = stream_settings.get("security", "none")
    network = stream_settings.get("network", "tcp")
    
    reality_settings = stream_settings.get("realitySettings", {})
    if isinstance(reality_settings, str):
        try: reality_settings = json.loads(reality_settings)
        except Exception: reality_settings = {}
        
    public_key = reality_settings.get("publicKey", "")
    fp = reality_settings.get("fingerprint", "chrome")
    
    short_ids = reality_settings.get("shortIds", [""])
    sid = short_ids if isinstance(short_ids, list) and short_ids else ""
    
    server_names = reality_settings.get("serverNames", ["://google.com"])
    sni = server_names if isinstance(server_names, list) and server_names else "://google.com"
    
    service_name = stream_settings.get("grpcSettings", {}).get("serviceName", "UpdateServiceApis")
    
    query_params = {"type": network, "security": security}
    if network == "grpc": query_params["serviceName"] = service_name
    if security == "reality":
        query_params.update({"pbk": public_key, "fp": fp, "sid": sid, "sni": sni, "authority": ""})
    if protocol == "vless" and network == "tcp" and security == "reality":
        query_params["flow"] = "xtls-rprx-vision"
        
    query_string = urllib.parse.urlencode(query_params)
    if protocol == "shadowsocks":
        inbound_settings = ib.get("settings", {})
        if isinstance(inbound_settings, str):
            try: inbound_settings = json.loads(inbound_settings)
            except Exception: inbound_settings = {}
        return f"ss://{inbound_settings.get('method', 'aes-256-gcm')}:{{uuid}}@{server_host}:{port}#{urllib.parse.quote(remark)}-{{email}}"
        
    return f"{protocol}://{{uuid}}@{server_host}:{port}?{query_string}#{urllib.parse.quote(remark)}-{{email}}"
