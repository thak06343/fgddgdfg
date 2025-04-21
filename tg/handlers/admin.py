import asyncio
from collections import defaultdict
from tarfile import REGTYPE
from unittest.mock import CallableMixin

import aiohttp
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Filter
from asgiref.sync import sync_to_async
from aiogram.utils.markdown import hbold, hitalic, hcode
from django.utils import timezone

from .utils import changers_current_balance, balance_val, get_totals_reqs, req_adder, create_ltc_invoice, \
    check_invoice, create_limit_invoice, check_limit_invoice, get_ltc_usd_rate, transfer, changer_balance_with_invoices, \
    admin_balance, transfer_to_admin
from ..kb import changer_panel_bottom
from ..models import TGUser, Invoice, Country, Req, WithdrawalMode, ShopOperator, ReqUsage, Promo
from ..text import main_page_text, add_new_req_text, settings_text, shop_stats_text, order_operator_text
from django.db.models import Sum, Count, Q, FloatField
from django.db.models.functions import Coalesce
from datetime import datetime, date

router = Router()

class IsAdmin(Filter):
    async def __call__(self, msg: Message):
        try:
            user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
            return user.is_admin
        except Exception as e:
            return False

router.message.filter(IsAdmin())

@router.message(F.text == "🐙 Главное")
async def main_admin(msg: Message):
    user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
    balance, adm_invoices =  await admin_balance(user)
    text = f"💰 *Баланс:* *${round(balance, 2)}*\n"
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⚡️ 𝑳𝑻𝑪", callback_data=f"admin_order_to_withdraw"))
    await msg.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


class WithdrawToAdminState(StatesGroup):
    awaiting_ltc_req = State()

@router.callback_query(F.data == "admin_order_to_withdraw")
async def shop_order_to_withdraw(call: CallbackQuery, state: FSMContext):
    await state.set_state(WithdrawToAdminState.awaiting_ltc_req)
    await call.message.answer("💸 Введите кошелек LTC для вывода:")

@router.message(WithdrawToAdminState.awaiting_ltc_req)
async def awaiting_ltc_to_send_shop(msg: Message, state: FSMContext):
    user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
    try:
        ltc_address = msg.text.strip()
        balance, adm_invoices =  await admin_balance(user)
        try:
            ltc_usdt_price = await get_ltc_usd_rate()
        except Exception as e:
            await msg.answer(f"❌ Не удалось получить курс LTC. Попробуйте позже.\n{e}")
            return
        ltc_amount = balance / ltc_usdt_price
        amount_in_satoshi = int(ltc_amount * 100_000_000)
        pack = await sync_to_async(WithdrawalMode.objects.create)(user=user, active=True, requisite=ltc_address,
                                                                  ltc_amount=ltc_amount)
        await sync_to_async(pack.invoices.add)(*adm_invoices)
        result = await transfer_to_admin(amount_in_satoshi, ltc_address, pack.id)
        await msg.answer(result)
        await state.clear()
    except Exception as e:
        print(e)

@router.message(F.text == "♟ Курсы")
async def manage_courses(msg: Message):
    countries = await sync_to_async(Country.objects.all)()
    builder = InlineKeyboardBuilder()
    text = ""
    for country in countries:
        builder.add(InlineKeyboardButton(text=f"{country.flag} {country.country.upper()}", callback_data=f"change_course_{country.id}"))
        text += f"{country.flag} {country.country.upper()}\n"
        text += f"KZT-{country.country.upper()} = {country.kzt_to_fiat}\n"
        text += f"{country.country.upper()}-USDT = {country.fiat_to_usdt}\n"
        text += f"{country.country.upper()}-USDT = {country.fiat_to_usdt_for_shop} (SHOP PRICE)\n\n"
    builder.adjust(2)
    await msg.answer(text if text else "123", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("change_course_"))
async def change_courses(call: CallbackQuery):
    data = call.data.split("_")
    country = await sync_to_async(Country.objects.get)(id=data[2])
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=f"KZT - {country.country.upper()} ({country.kzt_to_fiat})", callback_data=f"change_kzt_to_fiat_{country.id}"))
    builder.add(InlineKeyboardButton(text=f"{country.country.upper()}-USDT = ({country.fiat_to_usdt})", callback_data=f"change_fiat_to_usdt_{country.id}"))
    builder.add(InlineKeyboardButton(text=f"{country.country.upper()}-USDT = ({country.fiat_to_usdt_for_shop}) SHOP", callback_data=f"change_fiat_to_usdt_for_shop_{country.id}"))
    builder.adjust(1)
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())

class ChangeCountryCoursesState(StatesGroup):
    awaiting_kzt_to_fiat = State()
    awaiting_fiat_to_usdt = State()
    awaiting_fiat_to_usdt_for_shop = State()

@router.callback_query(F.data.startswith("change_kzt_to_fiat_"))
async def change_kzt_to_fiat(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    country = await sync_to_async(Country.objects.get)(id=data[4])
    await state.set_state(ChangeCountryCoursesState.awaiting_kzt_to_fiat)
    await state.update_data(country_id=country.id)
    await call.message.answer(f"Введите значение для KZT - {country.country.upper()}:\n\nТекущее значение = {country.kzt_to_fiat}")

@router.message(ChangeCountryCoursesState.awaiting_kzt_to_fiat)
async def awaiting_kzt_to_fiat(msg: Message, state: FSMContext):
    try:
        new_course = float(msg.text)
        data = await state.get_data()
        country_id = data.get("country_id")
        country = await sync_to_async(Country.objects.get)(id=country_id)
        country.kzt_to_fiat = new_course
        country.save()
        await state.clear()
        await msg.answer(f"Курс KZT - {country.country.upper()} изменен на {new_course}")
    except Exception as e:
        await msg.answer("Введите корректное значение, например 1.5, 2, 3.4")

@router.callback_query(F.data.startswith("change_fiat_to_usdt_"))
async def change_kzt_to_fiat(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    country = await sync_to_async(Country.objects.get)(id=data[4])
    await state.set_state(ChangeCountryCoursesState.awaiting_fiat_to_usdt)
    await state.update_data(country_id=country.id)
    await call.message.answer(f"Введите значение для {country.country.upper()} - USDT:\n\nТекущее значение = {country.awaiting_fiat_to_usdt}")

@router.message(ChangeCountryCoursesState.awaiting_fiat_to_usdt)
async def awaiting_kzt_to_fiat(msg: Message, state: FSMContext):
    try:
        new_course = float(msg.text)
        data = await state.get_data()
        country_id = data.get("country_id")
        country = await sync_to_async(Country.objects.get)(id=country_id)
        country.awaiting_fiat_to_usdt = new_course
        country.save()
        await state.clear()
        await msg.answer(f"Курс {country.country.upper()} - USDT изменен на {new_course}")
    except Exception as e:
        await msg.answer("Введите корректное значение, например 1.5, 2, 3.4")

@router.callback_query(F.data.startswith("change_fiat_to_usdt_for_shop_"))
async def fiat_to_usdt_for_shop(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    country = await sync_to_async(Country.objects.get)(id=data[6])
    await state.set_state(ChangeCountryCoursesState.awaiting_fiat_to_usdt_for_shop)
    await state.update_data(country_id=country.id)
    await call.message.answer(f"Введите значение для {country.country.upper()} - USDT(SHOP):\n\nТекущее значение = {country.fiat_to_usdt_for_shop}")

@router.message(ChangeCountryCoursesState.awaiting_fiat_to_usdt)
async def awaiting_kzt_to_fiat(msg: Message, state: FSMContext):
    try:
        new_course = float(msg.text)
        data = await state.get_data()
        country_id = data.get("country_id")
        country = await sync_to_async(Country.objects.get)(id=country_id)
        country.fiat_to_usdt_for_shop = new_course
        country.save()
        await state.clear()
        await msg.answer(f"Курс {country.country.upper()} - USDT(SHOP) изменен на {new_course}")
    except Exception as e:
        await msg.answer("Введите корректное значение, например 1.5, 2, 3.4")

@router.message(F.text == "🏵 Промо")
async def admin_promo_create(msg: Message):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="➕ Новый магазин", callback_data="admin_new_shop_promo"))
    builder.add(InlineKeyboardButton(text="➕ Новый оператор обмена", callback_data="admin_new_operator_promo"))
    builder.adjust(1)
    text = "Выберите где хотите создать промокод:"
    await msg.answer(text, reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin_new_shop_promo")
async def admin_new_shop_promo(call: CallbackQuery, bot: Bot):
    new_promo = await sync_to_async(Promo.objects.create)(type="new_shop")
    bot_info = await bot.get_me()
    bot_username = bot_info.username
    link = f"https://t.me/{bot_username}?start={new_promo.code}"
    await call.message.answer(f"`{link}`\n\nОтправьте ссылку новому магазину!", parse_mode="Markdown")

@router.callback_query(F.data == "admin_new_operator_promo")
async def admin_new_shop_promo(call: CallbackQuery, bot: Bot):
    new_promo = await sync_to_async(Promo.objects.create)(type="new_changer")
    bot_info = await bot.get_me()
    bot_username = bot_info.username
    text = f"https://t.me/{bot_username}?start={new_promo.code}"
    await call.message.answer(f"`{text}`\n\nОтправьте ссылку новому оператору!", parse_mode="Markdown")