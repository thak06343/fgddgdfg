import asyncio
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery, ReactionTypeEmoji
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Filter, Command
from asgiref.sync import sync_to_async
from aiogram.utils.markdown import hbold, hcode
from .utils import changers_current_balance, balance_val, get_totals_reqs, req_adder, create_ltc_invoice, \
    check_invoice, create_limit_invoice, check_limit_invoice, get_ltc_usd_rate, transfer, changer_balance_with_invoices, \
    req_invoices, IsLtcReq, operator_mode_invoice_balances
from ..kb import changer_panel_bottom
from ..models import TGUser, Invoice, Country, Req, WithdrawalMode, ReqUsage, OperatorMode
from ..text import main_page_text, add_new_req_text, settings_text, shop_stats_text, changer_invoice_text
from django.db.models import Sum, FloatField
from django.db.models.functions import Coalesce
from datetime import datetime
router = Router()

class IsOperFilter(Filter):
    async def __call__(self, msg: Message):
        try:
            user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
            return user.is_changer
        except Exception as e:
            return False

router.message.filter(IsOperFilter())

@router.callback_query(F.data.startswith("accept_invoice_"))
async def accepting_invoice(call: CallbackQuery, bot: Bot, state: FSMContext):
    data = call.data.split("_")
    # course = await sync_to_async(Course.objects.first)()
    invoice_id = data[2]
    invoice = await sync_to_async(Invoice.objects.get)(id=invoice_id)
    user = await sync_to_async(TGUser.objects.get)(user_id=call.from_user.id)
    if invoice.amount_in_kzt:
        if invoice.req.user == user:
            invoice.accepted = True
            invoice.save()
            builder = InlineKeyboardBuilder()
            country = await sync_to_async(Country.objects.get)(id=invoice.req.country.id)
            if country:
                amount_in_fiat = invoice.amount_in_fiat
                amount_in_usdt = invoice.amount_in_usdt_for_changer
                builder.add(InlineKeyboardButton(text=f"✅ +{int(amount_in_fiat)} (${round(amount_in_usdt, 2)})"
                                                      f" *{invoice.req.cart[-4:]}", callback_data="none"))
                await call.message.edit_reply_markup(reply_markup=builder.as_markup())
                try:
                    await bot.unpin_chat_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
                except Exception as e:
                    print(e)
        else:
            reqs = await sync_to_async(Req.objects.filter)(user=user, archived=False)
            builder = InlineKeyboardBuilder()
            for req in reqs:

                short_name = req.name[:3].upper()
                last_digits = req.cart[-4:] if req.cart and len(req.cart) >= 4 else "****"
                builder.add(
                    InlineKeyboardButton(text=f"✅ ({invoice.amount_in_kzt}T) {short_name} *{last_digits}",
                                         callback_data=f"sended_invoice_{invoice.id}_{req.id}"))
            builder.adjust(2)
            builder.row(InlineKeyboardButton(text="< Назад", callback_data=f"changer_back_to_accepts_{invoice.id}"))
            await call.message.edit_reply_markup(reply_markup=builder.as_markup())
    else:
        if invoice.req.user == user:
            await call.answer("Укажите сколько пришло в вашей валюте", show_alert=True)
            await state.set_state(AcceptFiat.awaiting_amount)
            await state.update_data(invoice_id=invoice_id)
        else:
            reqs = await sync_to_async(Req.objects.filter)(user=user, archived=False)
            builder = InlineKeyboardBuilder()
            for req in reqs:
                short_name = req.name[:3].upper()
                last_digits = req.cart[-4:] if req.cart and len(req.cart) >= 4 else "****"
                builder.add(
                    InlineKeyboardButton(text=f"✅ ({invoice.amount_in_fiat}{invoice.req.country.country}) {short_name} *{last_digits}",
                                         callback_data=f"sended_invoice_{invoice.id}_{req.id}"))
            builder.adjust(2)
            builder.row(InlineKeyboardButton(text="< Назад", callback_data=f"changer_back_to_accepts_{invoice.id}"))
            await call.message.edit_reply_markup(reply_markup=builder.as_markup())

class AcceptFiat(StatesGroup):
    awaiting_amount = State()

@router.message(AcceptFiat.awaiting_amount)
async def accept_fiat(msg: Message, state: FSMContext, bot: Bot):
    try:
        amount = int(msg.text)
        data = await state.get_data()
        invoice_id = data.get("invoice_id")
        invoice = await sync_to_async(Invoice.objects.get)(id=invoice_id)
        reaction = ReactionTypeEmoji(emoji="👍")
        try:
            await bot.set_message_reaction(chat_id=msg.chat.id, reaction=[reaction],
                                           message_id=msg.message_id)
        except Exception as e:
            print(e)
        invoice.accepted = True
        invoice.amount_in_fiat = amount
        country = invoice.req.country
        if country.country != "uzs":
            fiat = amount
            kzt = fiat * country.kzt_to_fiat
            usdt_for_changer = fiat / country.fiat_to_usdt
            usdt_for_shop = fiat / country.fiat_to_usdt_for_shop
        else:
            fiat = amount
            kzt = fiat / country.kzt_to_fiat
            usdt_for_changer = fiat / country.fiat_to_usdt
            usdt_for_shop = fiat / country.fiat_to_usdt_for_shop
        if kzt:
            invoice.amount_in_kzt = kzt
        invoice.amount_in_usdt = usdt_for_shop
        invoice.amount_in_usdt_for_changer = usdt_for_changer
        invoice.save()
        await state.clear()
    except Exception as e:
        print(e)

@router.callback_query(F.data.startswith("sended_invoice_"))
async def sended_invoice(call: CallbackQuery, bot: Bot, state: FSMContext):
    data = call.data.split("_")
    invoice_id = data[2]
    req_id = data[3]
    invoice = await sync_to_async(Invoice.objects.get)(id=invoice_id)
    req = await sync_to_async(Req.objects.get)(id=req_id)
    invoice.req = req
    invoice.save()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="< Назад", callback_data=f"changer_back_to_accepts_{invoice.id}"))
    await call.answer(f"Введите сумму в {invoice.req.country.country}")
    await state.set_state(AcceptFiat.awaiting_amount)
    await state.update_data(invoice_id=invoice_id)


@router.message(F.text == "📍 Главное")
async def main_page(msg: Message):
    user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
    balance, ref_balance = await changers_current_balance(user)
    text = main_page_text.format(balance=round(balance + ref_balance, 2))
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⚡️ 𝑳𝑻𝑪", callback_data=f"take_zp_ltc"))
    # builder.add(InlineKeyboardButton(text="📥 К А Р Т А ", callback_data=f"take_zp_cart"))
    builder.adjust(2)
    await msg.answer(text, parse_mode="Markdown", reply_markup=builder.as_markup())

class WithdrawToChangerState(StatesGroup):
    awaiting_ltc_req = State()

@router.callback_query(F.data == "take_zp_ltc")
async def take_zp_ltc(call: CallbackQuery, state: FSMContext):
    user = await sync_to_async(TGUser.objects.get)(user_id=call.from_user.id)
    balance, ref_balance = await changers_current_balance(user)
    balance += ref_balance
    if balance <= 9:
        await call.answer("Недостаточный баланс! Вывод от 10$", show_alert=True)
    else:
        await state.set_state(WithdrawToChangerState.awaiting_ltc_req)
        await call.message.answer("💸 Введите кошелек LTC для вывода:")

@router.message(WithdrawToChangerState.awaiting_ltc_req)
async def withdraw_to_changer(msg: Message, state: FSMContext):
    try:
        is_ltc_req = await IsLtcReq(msg.text)
        if is_ltc_req:
            await state.clear()
            user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
            ltc_address = msg.text.strip()
            main_balance, main_invs, ref_balance, ref_invs = await changer_balance_with_invoices(user)
            balance = main_balance + ref_balance
            if balance  < 10:
                await msg.answer("Недостаточный баланс! Вывод от 10$")
                return

            try:
                ltc_usdt_price = await get_ltc_usd_rate()
            except Exception as e:
                await msg.answer(f"❌ Не удалось получить курс LTC. Попробуйте позже.\n{e}")
                return

            ltc_amount = balance / ltc_usdt_price
            amount_in_satoshi = int(ltc_amount * 100_000_000)
            pack = await sync_to_async(WithdrawalMode.objects.create)(user=user, active=True, requisite=ltc_address, ltc_amount=ltc_amount)
            for main_inv in main_invs:
                pack.invoices.add(main_inv)
            await sync_to_async(pack.ref_invoices.add)(*ref_invs)
            result = await transfer(amount_in_satoshi, ltc_address, pack.id)
            await msg.answer(result, parse_mode="Markdown")
        else:
            await msg.answer("Неверный LTC адрес, попробуйте заново")
            await state.clear()
    except Exception as e:
        print(e)

class AddReqState(StatesGroup):
    awaiting_name = State()
    awaiting_cart = State()


@router.callback_query(F.data.startswith("add_new_req_"))
async def add_new_req(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    country_id = data[3]
    await state.set_state(AddReqState.awaiting_cart)
    await state.update_data(country_id=country_id)
    await call.message.answer("Укажите номер карты: ")


@router.message(AddReqState.awaiting_cart)
async def awaiting_cart(msg: Message, state: FSMContext):
    try:
        cart = msg.text.strip()

        if len(cart) == 16:
            req = await sync_to_async(Req.objects.filter)(cart=cart)
            if req:
                await msg.answer("Карта уже добавлена, попробуйте заново")
                await state.clear()
                return
            await state.update_data(cart=cart)
            await msg.answer("Укажите имя фамилию на латинице, указанное на карте: ")
            await state.set_state(AddReqState.awaiting_name)
        else:
            await msg.answer("Попробуйте еще раз!\n\nНапример: _хххх хххх хххх хххх_", parse_mode="Markdown")
    except Exception as e:
        print(e)


@router.message(AddReqState.awaiting_name)
async def awaiting_cart_name(msg: Message, state: FSMContext):
    try:
        user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
        data = await state.get_data()
        cart = data.get("cart")
        country_id = data.get("country_id")
        country = await sync_to_async(Country.objects.get)(id=country_id)
        name = msg.text.upper()
        new_req = await sync_to_async(Req.objects.create)(user=user, name=name, active=False, cart=cart, country=country)
        await msg.answer("🎊 Кошелек добавлен!")
        await state.clear()
    except Exception as e:
        print(e)


@router.message(F.text.startswith("P2P: "))
async def changer_settings(msg: Message, bot: Bot):
    user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
    reqs = await sync_to_async(Req.objects.filter)(user=user)
    if reqs:
        total_amount_val, awaiting_usdt = await balance_val(user)
        val_in_usdt = total_amount_val + awaiting_usdt
        ostatok = user.limit - val_in_usdt

        text = f"🔰 {hbold('Лимит')}: {hbold(user.limit)} USDT \n\n"
        text += f"🧩 {hbold('Фиатные счета')}:\n"
        total_usd = 0
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="♨️ Вкл/Выкл режим P2P", callback_data="on_off_p2p"))
        builder.adjust(1)
        for req in reqs:
            totals = await get_totals_reqs(req)
            total_usdt = totals['total_usdt']
            total_fiat = totals['total_fiat']
            if total_usdt >= 1:

                total_usd += total_usdt
                short_name = req.name[:3].upper()
                last_digits = req.cart[-4:] if req.cart and len(req.cart) >= 4 else "****"

                text += (
                    f"💳 {hbold(f'{short_name} *{last_digits}')} {hbold(req.country.country).upper()}\n"
                    f"   🌐 {hbold('ФИАТ')}: {hcode(round(total_fiat, 2))}\n"
                    f"   💵 {hbold('USDT')}: {hcode(round(total_usdt, 2))}\n\n"
                )
                # builder.add(InlineKeyboardButton(text=f'{short_name} *{last_digits} (${round(total_usdt, 2)})', callback_data=f"send_to_bank_{req.id}"))
        builder.adjust(2)
        builder.row(InlineKeyboardButton(text=f"🔄 Завершить круг по всем 💳 ${round(total_usd, 2)}", callback_data=f"close_all_reqs"))
        builder.adjust(1)
        text += f"📊 {hbold('Итого')}:\n"
        text += f"   💵 {hbold('USDT')}: {hbold(round(total_usd, 2))}\n"
        text += f"   🔰 {hbold('Лимит')}: {hcode(round(ostatok, 2))} \n"


        await msg.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
    else:
        await req_adder(msg)

@router.callback_query(F.data == "on_off_p2p")
async def on_off_p2p(call: CallbackQuery):
    user = await sync_to_async(TGUser.objects.get)(user_id=call.from_user.id)
    active_reqs = await sync_to_async(Req.objects.filter)(active=True, user=user, archived=False)
    total_amount_val, awaiting_usdt = await balance_val(user)
    val_in_usdt = total_amount_val + awaiting_usdt
    ostatok = user.limit - val_in_usdt
    if not active_reqs:
        if ostatok > 25:
            reqs = await sync_to_async(Req.objects.filter)(user=user, archived=False)
            for req in reqs:
                req.active = True
                await sync_to_async(req.save)()
            bottom = await changer_panel_bottom(user)
            await call.message.answer("🟢  _Включен P2P режим!_", reply_markup=bottom, parse_mode="Markdown")
        else:
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(text="🔰 Поднять лимит", callback_data="hoja_limit"))
            text = (f"   🧮 {hbold('Валидная сумма')}: {hbold(f'${round(ostatok, 2)}')}\n\n"
                         f"\n❗️ Включить P2P режим не удалось!")

            await call.message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    elif active_reqs:
        for req in active_reqs:
            req.active = False
            await sync_to_async(req.save)()
        bottom = await changer_panel_bottom(user)
        await call.message.answer("✔️ _Вы вышли из режима P2P_", reply_markup=bottom, parse_mode="Markdown")
    return

@router.callback_query(F.data.startswith("close_all_reqs"))
async def close_all_reqs(call: CallbackQuery, bot: Bot):
    user = await sync_to_async(TGUser.objects.get)(user_id=call.from_user.id)

    total_amount_val, invoice_list = await sync_to_async(lambda: (
        Invoice.objects.filter(accepted=True, sent_bank=False, req__user=user)
        .aggregate(total=Coalesce(Sum('amount_in_usdt_for_changer'), 0.0, output_field=FloatField()))['total'],
        list(Invoice.objects.filter(accepted=True, sent_bank=False, req__user=user))
    ))()
    if total_amount_val and invoice_list:
        try:
            active_wm = await sync_to_async(WithdrawalMode.objects.filter)(user=user, active=True)
            if active_wm:
                return
        except Exception as e:
            print(e)
        invoice_info, ltc_amount = await create_ltc_invoice(total_amount_val)



        invoice_id = invoice_info['invoice']
        ltc_address = invoice_info['address']
        expire = invoice_info['expire']
        pack = await sync_to_async(WithdrawalMode.objects.create)(user=user, active=True, requisite=ltc_address, ltc_amount=ltc_amount)
        await sync_to_async(pack.invoices.add)(*invoice_list)
        iso_expire_time = expire
        dt = datetime.fromisoformat(iso_expire_time)
        formatted_time = dt.strftime("%d %B %Y, %H:%M")
        message = (
            f"🧾 <b>Заявка №{pack.id}</b>\n\n"
            f"💵 Сумма в USD: <b>{round(total_amount_val, 2)} $</b>\n"
            f"🪙 Сумма в LTC: <b>{ltc_amount:.7f} LTC</b>\n\n"
            f"📬 Адрес для перевода:\n<code>{ltc_address}</code>\n\n"
            f"⏳ Действителен до: <b>{formatted_time}</b>\n"
        )

        asyncio.create_task(check_invoice(pack.id, invoice_id, bot))
        await call.message.answer(message, parse_mode="HTML")

@router.callback_query(F.data.startswith("send_to_bank_"))
async def send_to_bank_req(call: CallbackQuery, bot: Bot):
    await call.answer("Кнопка не доступна")
    # user = await sync_to_async(TGUser.objects.get)(user_id=call.from_user.id)
    # data = call.data.split("_")
    # req_id = data[3]
    # req = await sync_to_async(Req.objects.get)(id=req_id)
    #
    # total_amount_val, invoice_list = await sync_to_async(lambda: (
    #     Invoice.objects.filter(accepted=True, sent_bank=False, req=req)
    #     .aggregate(total=Coalesce(Sum('amount_in_usdt_for_changer'), 0.0, output_field=FloatField()))['total'],
    #     list(Invoice.objects.filter(accepted=True, sent_bank=False, req__user=user))
    # ))()
    # if total_amount_val and invoice_list:
    #     try:
    #         active_wm = await sync_to_async(WithdrawalMode.objects.filter)(user=user, active=True)
    #         if active_wm:
    #             return
    #     except Exception as e:
    #         print(e)
    #
    #     invoice_info, ltc_amount = await create_ltc_invoice(total_amount_val)
    #
    #     invoice_id = invoice_info['invoice']
    #     ltc_address = invoice_info['address']
    #     expire = invoice_info['expire']
    #     pack = await sync_to_async(WithdrawalMode.objects.create)(user=user, active=True, requisite=ltc_address,
    #                                                               ltc_amount=ltc_amount)
    #     await sync_to_async(pack.invoices.add)(*invoice_list)
    #     iso_expire_time = expire
    #     dt = datetime.fromisoformat(iso_expire_time)
    #     formatted_time = dt.strftime("%d %B %Y, %H:%M")
    #     message = (
    #         f"🧾 <b>Заявка №{pack.id}</b>\n\n"
    #         f"💵 Сумма в USD: <b>{round(total_amount_val, 2)} $</b>\n"
    #         f"🪙 Сумма в LTC: <b>{ltc_amount:.7f} LTC</b>\n\n"
    #         f"📬 Адрес для перевода:\n<code>{ltc_address}</code>\n\n"
    #         f"⏳ Действителен до: <b>{formatted_time}</b>\n"
    #     )
    #
    #     asyncio.create_task(check_invoice(pack.id, invoice_id, bot))
    #     await call.message.answer(message, parse_mode="HTML")

@router.message(F.text == "⚙️ Настройки")
async def changer_settings(msg: Message):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="➕ Фиатный счет", callback_data="choosing_country_req"))
    builder.add(InlineKeyboardButton(text="♾️ Управление", callback_data="manage_reqs"))
    builder.add(InlineKeyboardButton(text="🔰 Поднять лимит", callback_data="hoja_limit"))
    builder.adjust(1)
    await msg.answer(settings_text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "choosing_country_req")
async def choose_and_add_req(call: CallbackQuery):
    countries = await sync_to_async(Country.objects.all)()
    builder = InlineKeyboardBuilder()
    for country in countries:
        builder.add(InlineKeyboardButton(text=f"{country.flag} {country.country.upper()}",
                                         callback_data=f"add_new_req_{country.id}"))
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="< Назад", callback_data="back_to_settings"))
    await call.message.edit_text(add_new_req_text, reply_markup=builder.as_markup())

@router.callback_query(F.data == "back_to_settings")
async def back_to_settings(call: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="➕ Фиатный счет", callback_data="choosing_country_req"))
    builder.add(InlineKeyboardButton(text="♾️ Управление", callback_data="manage_reqs"))
    builder.add(InlineKeyboardButton(text="🔰 Поднять лимит", callback_data="hoja_limit"))
    builder.adjust(1)
    await call.message.edit_text(settings_text, reply_markup=builder.as_markup())

@router.callback_query(F.data == "hoja_limit")
async def hoja_limit(call: CallbackQuery, bot: Bot):
    user = await sync_to_async(TGUser.objects.get)(user_id=call.from_user.id)
    invoice_info, ltc_amount = await create_limit_invoice()


    invoice_id = invoice_info['invoice']
    ltc_address = invoice_info['address']
    expire = invoice_info['expire']
    iso_expire_time = expire
    dt = datetime.fromisoformat(iso_expire_time)
    formatted_time = dt.strftime("%d %B %Y, %H:%M")
    pack = await sync_to_async(WithdrawalMode.objects.create)(user=user, active=True, requisite=ltc_address, ltc_amount=ltc_amount)
    message = (
        f"🧾 <b>Заявка №{pack.id}</b>\n\n"
        f"💵 Сумма в USD: <b>{round(50, 2)} $</b>\n"
        f"🪙 Сумма в LTC: <b>{ltc_amount:.8f} LTC</b>\n\n"
        f"📬 Адрес для перевода:\n<code>{ltc_address}</code>\n\n"
        f"⏳ Действителен до: <b>{formatted_time}</b>\n"
    )
    asyncio.create_task(check_limit_invoice(pack.id, invoice_id, bot))
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_limit_{pack.id}"))
    await call.message.answer(message, parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("cancel_limit_"))
async def cancel_limit_invoice(call: CallbackQuery):
    data = call.data.split("_")
    pack = await sync_to_async(WithdrawalMode.objects.get)(id=data[2])
    pack.active = False
    pack.save()
    await call.message.delete()
    await call.message.answer("✔️ _Заявка на повышение лимита отменена!_", parse_mode="Markdown")


@sync_to_async
def get_user_reqs(user_id, offset, limit):
    return list(Req.objects.filter(user__user_id=str(user_id)).order_by('archived')[offset:offset + limit])


@sync_to_async
def count_user_reqs(user_id):
    return Req.objects.filter(user__user_id=str(user_id)).count()

@router.callback_query(F.data.startswith("manage_reqs"))
async def manage_reqs(call: CallbackQuery):
    data = call.data.split("_")
    page = int(data[2]) if len(data) > 2 else 1
    per_page = 30
    offset = (page - 1) * per_page

    total = await count_user_reqs(user_id=call.from_user.id)
    reqs = await get_user_reqs(call.from_user.id, offset, per_page)

    builder = InlineKeyboardBuilder()
    for req in reqs:
        short_name = req.name[:3].upper()
        last_digits = req.cart[-4:] if req.cart and len(req.cart) >= 4 else "****"
        builder.add(InlineKeyboardButton(text=f"{'🟢' if req.active else '⚫️'} {short_name} *{last_digits} "
                                              f"{'🔒' if req.archived else ' '}", callback_data=f"manage_req_{req.id}"))
    if page > 1:
        builder.add(InlineKeyboardButton(text="⬅️", callback_data=f"manage_reqs_{page - 1}"))
    if offset + per_page < total:
        builder.add(InlineKeyboardButton(text="➡️", callback_data=f"manage_reqs_{page + 1}"))
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="< Назад", callback_data="back_to_settings"))
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("manage_req_"))
async def manage_req(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    req = await sync_to_async(Req.objects.get)(id=data[2])
    usdt, invs = await req_invoices(req)
    short_name = req.name[:3].upper()
    last_digits = req.cart
    text = (f"{short_name} {last_digits}\n"
            f"${round(usdt, 2)} ({len(invs)})\n"
            f"`{req.info if req.info else 'Без заметки'}`")
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Добавить описание", callback_data=f"add_description_to_req_{req.id}"))
    builder.add(InlineKeyboardButton(text=f"{'🟢' if req.active else '⚫️'}", callback_data=f"activate_req_{req.id}"))
    if not req.archived:
        text += "\n\n❌ Удален"
        builder.add(InlineKeyboardButton(text="❌ Удалить", callback_data=f"changer_archive_req_{req.id}"))
    if req.archived:
        builder.add(InlineKeyboardButton(text="🟢 Восстановить", callback_data=f"changer_restore_req_{req.id}"))
    builder.add(InlineKeyboardButton(text="Котегории", callback_data=f"manage_categories_req_{req.id}"))
    builder.row(InlineKeyboardButton(text="< Назад", callback_data="manage_reqs"))
    builder.adjust(1)
    await call.message.edit_text(text=text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await state.clear()

@router.callback_query(F.data.startswith("manage_categories_req_"))
async def manage_categories_req(call: CallbackQuery):
    data = call.data.split("_")
    req = await sync_to_async(Req.objects.get)(id=data[3])
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=f"💳 Kaspi {'🟢' if req.kaspi else '⚫️'} ",
                                     callback_data=f"change_category_kaspi_{req.id}"))
    builder.add(InlineKeyboardButton(text=f"🛒 БезKaspi {'🟢' if req.bez_kaspi else '⚫️'} ",
                                     callback_data=f"change_category_bezkaspi_{req.id}"))
    builder.add(InlineKeyboardButton(text=f"🐤 Qiwi {'🟢' if req.qiwi else '⚫️'} ",
                                     callback_data=f"change_category_qiwi_{req.id}"))
    builder.add(InlineKeyboardButton(text=f"🏧 Terminal {'🟢' if req.terminal else '⚫️'} ",
                                     callback_data=f"change_category_terminal_{req.id}"))
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="< Назад", callback_data=f"manage_req_{req.id}"))
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("change_category_"))
async def change_category(call: CallbackQuery):
    data = call.data.split("_")
    req = await sync_to_async(Req.objects.get)(id=data[3])
    category = data[2]
    if category in ["kaspi", "bezkaspi", "qiwi", "terminal"]:
        field_name = category if category != "bezkaspi" else "bez_kaspi"
        current_value = getattr(req, field_name)
        setattr(req, field_name, not current_value)
        await sync_to_async(req.save)()
    else:
        await call.answer("Неизвестная категория", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=f"💳 Kaspi {'🟢' if req.kaspi else '⚫️'} ",
                                     callback_data=f"change_category_kaspi_{req.id}"))
    builder.add(InlineKeyboardButton(text=f"🛒 БезKaspi {'🟢' if req.bez_kaspi else '⚫️'} ",
                                     callback_data=f"change_category_bezkaspi_{req.id}"))
    builder.add(InlineKeyboardButton(text=f"🐤 Qiwi {'🟢' if req.qiwi else '⚫️'} ",
                                     callback_data=f"change_category_qiwi_{req.id}"))
    builder.add(InlineKeyboardButton(text=f"🏧 Terminal {'🟢' if req.terminal else '⚫️'} ",
                                     callback_data=f"change_category_terminal_{req.id}"))
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="< Назад", callback_data=f"manage_req_{req.id}"))
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("changer_restore_req_"))
async def changer_restore_req(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    req = await sync_to_async(Req.objects.get)(id=data[3])
    usdt, invs = await req_invoices(req)
    short_name = req.name[:3].upper()
    last_digits = req.cart
    text = (f"{short_name} {last_digits}\n"
            f"${round(usdt, 2)} ({len(invs)})\n"
            f"`{req.info if req.info else 'Без заметки'}`")
    req.archived = False
    req.save()
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Добавить описание", callback_data=f"add_description_to_req_{req.id}"))
    builder.add(InlineKeyboardButton(text=f"{'🟢' if req.active else '⚫️'}", callback_data=f"activate_req_{req.id}"))
    if not req.archived:
        builder.add(InlineKeyboardButton(text="❌ Удалить", callback_data=f"changer_archive_req_{req.id}"))
    if req.archived:
        text += "\n\n❌ Удален"
        builder.add(InlineKeyboardButton(text="🟢 Восстановить", callback_data=f"changer_restore_req_{req.id}"))
    builder.row(InlineKeyboardButton(text="< Назад", callback_data="manage_reqs"))
    builder.adjust(1)
    await call.message.edit_text(text=text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await state.clear()

@router.callback_query(F.data.startswith("changer_archive_req_"))
async def changer_archive_req(call: CallbackQuery):
    data = call.data.split("_")
    req = await sync_to_async(Req.objects.get)(id=data[3])
    req.archived = True
    req.save()
    await call.answer("Архивировано")

@router.callback_query(F.data.startswith("add_description_to_req_"))
async def add_description_to_req(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="< Назад", callback_data=f"manage_req_{data[4]}"))
    await call.message.edit_text("Введите описание:", reply_markup=builder.as_markup())
    await state.set_state(AddDescriptionToReqState.awaiting_desc)
    await state.update_data(req_id=data[4])


class AddDescriptionToReqState(StatesGroup):
    awaiting_desc = State()

@router.message(AddDescriptionToReqState.awaiting_desc)
async def adding_description_to_req(msg: Message, state: FSMContext):
    data = await state.get_data()
    req_id = data.get("req_id")
    req = await sync_to_async(Req.objects.get)(id=req_id)
    if msg.text:
        req.info = msg.text
        req.save()
        await state.clear()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="< Назад", callback_data=f"manage_reqs"))
    await msg.answer("Описание успешно добавлено", reply_markup=builder.as_markup())

@router.message(F.text == "🔗 Реф система")
async def referral_system(msg: Message, bot: Bot):
    bot_info = await bot.get_me()
    bot_username = bot_info.username
    user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
    text = shop_stats_text.format(ref_link=f"https://t.me/{bot_username}?start={user.referral_code}")
    await msg.answer(text, parse_mode="Markdown")

@router.callback_query(F.data.startswith("activate_req_"))
async def activate_req_edit(call: CallbackQuery):
    data = call.data.split("_")
    req = await sync_to_async(Req.objects.get)(id=data[2])
    user = await sync_to_async(TGUser.objects.get)(user_id=call.from_user.id)
    if req.active:
        req.active = False
        req.save()
        active_reqs = await sync_to_async(Req.objects.filter)(active=True, user=user)
        if not active_reqs:
            bottom = await changer_panel_bottom(user)
            await call.message.answer("✔️ _Вы вышли из режима P2P_", reply_markup=bottom, parse_mode="Markdown")
    elif not req.active:
        total_amount_val, awaiting_usdt = await balance_val(user)
        val_in_usdt = total_amount_val + awaiting_usdt
        ostatok = user.limit - val_in_usdt
        if ostatok > 25:
            active_reqs = await sync_to_async(Req.objects.filter)(active=True, user=user)
            req.active = True
            req.save()
            if len(active_reqs) == 1:
                bottom = await changer_panel_bottom(user)
                await call.message.answer("🟢  _Включен P2P режим!_", reply_markup=bottom, parse_mode="Markdown")
        else:
            text = f"   🧮 {hbold('Валидная сумма')}: {hbold(f'${round(ostatok, 2)}')}\n\n\n❗️ Задействовать фиатный счет не удалось!"
            await call.message.answer(text, parse_mode="HTML")

    reqs = await sync_to_async(Req.objects.filter)(user=user)
    builder = InlineKeyboardBuilder()
    for req in reqs:
        short_name = req.name[:3].upper()
        last_digits = req.cart[-4:] if req.cart and len(req.cart) >= 4 else "****"
        builder.add(InlineKeyboardButton(text=f"{'🟢' if req.active else '⚫️'} {short_name} *{last_digits}",
                                         callback_data=f"activate_req_{req.id}"))
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="< Назад", callback_data="back_to_settings"))
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("decline_invoice_"))
async def decline_invoice(call: CallbackQuery, bot: Bot):
    data = call.data.split("_")
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Фейковый чек", callback_data=f"declineinvoice_fakecheck_{data[2]}"))
    builder.add(InlineKeyboardButton(text="На фото не чек", callback_data=f"declineinvoice_notreceived_{data[2]}"))
    builder.add(InlineKeyboardButton(text="Не мой чек", callback_data=f"declineinvoice_notmine_{data[2]}"))
    builder.add(InlineKeyboardButton(text="< Назад", callback_data=f"changer_back_to_accepts_{data[2]}"))
    builder.adjust(1)
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())



@router.callback_query(F.data.startswith("declineinvoice_"))
async def decline_invoice(call: CallbackQuery, bot: Bot):
    data = call.data.split("_")
    status = data[1]
    invoice = await sync_to_async(Invoice.objects.get)(id=data[2])
    last_usage = await sync_to_async(ReqUsage.objects.get)(usage_inv=invoice)
    user = await sync_to_async(TGUser.objects.get)(user_id=call.from_user.id)
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✅", callback_data=f"admin_accept_invoice_{last_usage.usage_inv.id}_{last_usage.id}"))
    builder.add(InlineKeyboardButton(text="❌", callback_data=f"admindecline_invoice_{last_usage.usage_inv.id}_{last_usage.id}"))
    if user.is_admin:
        builder.adjust(2)
    else:
        admin = await sync_to_async(TGUser.objects.filter)(is_admin=True)
        admin = admin.first()
        text = (f"({invoice.id})KZT - {invoice.amount_in_kzt}T\n"
                f"USDT  - {invoice.amount_in_usdt_for_changer}\n"
                f"USDT(SHOP) - {invoice.amount_in_usdt}\n"
                f"operator - {invoice.req.user.username if invoice.req.user.username else invoice.req.user.first_name}\n"
                f"cart - {invoice.req.cart} {invoice.req.name}\n"
                f"shop - {invoice.shop.name}\n\n"
                f"❗️{status}")
        invoice.status = status
        invoice.save()
        try:
            check_msg = await bot.send_photo(chat_id=admin.user_id, photo=last_usage.photo if last_usage.photo else None,
                                             reply_markup=builder.as_markup(), caption=text)
        except Exception as e:
            check_msg = await bot.send_document(chat_id=admin.user_id, document=last_usage.photo if last_usage.photo else None, reply_markup=builder.as_markup(), caption=text)
        await call.answer("Информация отправлена")
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="✅", callback_data=f"accept_invoice_{invoice.id}"))
        builder.add(InlineKeyboardButton(text=f"Информация отправлена", callback_data="fdsgfdgdfh"))
        builder.adjust(1)
        await call.message.edit_reply_markup(reply_markup=builder.as_markup())

class ChangeFiatState(StatesGroup):
    awaiting_amount = State()

@router.callback_query(F.data.startswith("accept_and_change_fiat_"))
async def accept_and_change_fiat(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    invoice = await sync_to_async(Invoice.objects.get)(id=data[4])
    if not invoice.accepted:
        await state.set_state(ChangeFiatState.awaiting_amount)
        await state.update_data(invoice_id=data[4])
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="< Отмена", callback_data=f"changer_back_to_accepts_{data[4]}"))
        await call.message.edit_reply_markup(reply_markup=builder.as_markup())
    else:
        await call.answer("Инвойс уже принят")

@router.callback_query(F.data.startswith("changer_back_to_accepts_"))
async def changer_back_to_accepts(call: CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    data = call.data.split("_")
    invoice = await sync_to_async(Invoice.objects.get)(id=data[4])
    builder.add(InlineKeyboardButton(text=f"✅ ({invoice.amount_in_fiat}{invoice.req.country.country})",
                                     callback_data=f"accept_invoice_{invoice.id}"))
    # builder.add(
    #     InlineKeyboardButton(text=f"✍️ Др сумма", callback_data=f"accept_and_change_fiat_{invoice.id}"))
    builder.add(InlineKeyboardButton(text="❌", callback_data=f"decline_invoice_{invoice.id}"))
    builder.adjust(1)
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())
    await state.clear()

@router.message(ChangeFiatState.awaiting_amount)
async def awaiting_amount_invoice(msg: Message, state: FSMContext, bot: Bot):
    try:
        amount = int(msg.text)
        data = await state.get_data()
        invoice_id = data.get("invoice_id")
        invoice = await sync_to_async(Invoice.objects.get)(id=invoice_id)
        if not invoice.accepted:

            reaction = ReactionTypeEmoji(emoji="👍")
            try:
                await bot.set_message_reaction(chat_id=msg.chat.id, reaction=[reaction],
                                                   message_id=msg.message_id)
            except Exception as e:
                print(e)
            invoice.accepted = True
            invoice.amount_in_fiat = amount
            country = invoice.req.country
            if country.country != "uzs":
                fiat = amount
                usdt_for_changer = fiat / country.fiat_to_usdt
                usdt_for_shop = fiat / country.fiat_to_usdt_for_shop
            else:
                fiat = amount
                usdt_for_changer = fiat / country.fiat_to_usdt
                usdt_for_shop = fiat / country.fiat_to_usdt_for_shop
            invoice.amount_in_usdt = usdt_for_shop
            invoice.amount_in_usdt_for_changer = usdt_for_changer
            invoice.save()
        else:
            await msg.answer("Инвойс уже принят.")

        await state.clear()
    except Exception as e:
        print(e)

class OperatorModeState(StatesGroup):
    awaiting_amount = State()

@router.callback_query(F.data.startswith("in_mode_accept_"))
async def in_mode_accept(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    await state.update_data(invoice_id=data[3], check_chat_id=data[4], check_message_id=data[5], operator_mode_id=data[6])
    await state.set_state(OperatorModeState.awaiting_amount)
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=f"✅", callback_data=f"{call.data}"))
    await call.message.answer(f"Укажите сколько пришло в вашей валюте:")
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())

@router.message(OperatorModeState.awaiting_amount)
async def in_mode_awaiting_amount(msg: Message, state: FSMContext, bot: Bot):
    try:
        int(msg.text)
        data = await state.get_data()
        invoice_id = int(data.get("invoice_id"))
        check_chat_id = data.get("check_chat_id")
        check_message_id = int(data.get("check_message_id"))
        operator_mode_id = int(data.get("operator_mode_id"))
        operator_mode = await sync_to_async(OperatorMode.objects.get)(id=operator_mode_id)
        reaction = ReactionTypeEmoji(emoji="👍")
        invoice = await sync_to_async(Invoice.objects.get)(id=int(invoice_id))

        if not invoice.accepted:
            if invoice.req.country.country != "uzs":
                invoice.amount_in_fiat = int(msg.text)
                invoice.amount_in_usdt_for_changer = int(msg.text) / invoice.req.country.fiat_to_usdt
                invoice.amount_in_usdt = int(msg.text) / invoice.req.country.fiat_to_usdt_for_shop
            else:
                invoice.amount_in_fiat = int(msg.text) * invoice.req.country.kzt_to_fiat
                invoice.amount_in_usdt_for_changer = int(msg.text) / invoice.req.country.fiat_to_usdt
                invoice.amount_in_usdt = int(msg.text) / invoice.req.country.fiat_to_usdt_for_shop
            invoice.accepted = True
            invoice.save()
            operator_mode.invoices.add(invoice)
            all_current_invoices = operator_mode.invoices.all()
            balance = await operator_mode_invoice_balances(all_current_invoices)
            await bot.edit_message_text(chat_id=check_chat_id, message_id=check_message_id, text=f"+{invoice.amount_in_fiat} {invoice.req.country.country} (${int(balance)})")

            try:
                await bot.set_message_reaction(chat_id=msg.chat.id, reaction=[reaction],
                                               message_id=msg.message_id)
            except Exception as e:
                print(e)

            if balance >= operator_mode.max_amount:
                await bot.send_message(chat_id=check_chat_id, text="Вы достигли лимита, поменяйте реквизит!")
            usage = await sync_to_async(ReqUsage.objects.get)(usage_inv=invoice)
            usage.active = False
            usage.save()
        else:
            await msg.answer("Инвойс уже принят!")
        await state.clear()

    except Exception as e:
        print(e)


@router.message(Command("active"))
async def active_invoices_changer(msg: Message):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Все не принятые инвойсы", callback_data="all_changer_not_accepted_invoices"))
    await msg.answer("Принять платежи", reply_markup=builder.as_markup())

@sync_to_async
def get_changer_invoices(changer, offset, limit):
    return list(Invoice.objects.filter(req__user=changer, accepted=False).order_by('-date_used')[offset:offset + limit])

@sync_to_async
def count_changer_invoices(changer):
    return Invoice.objects.filter(accepted=False, req__user=changer).count()

@router.callback_query(F.data.startswith("all_changer_not_accepted_invoices"))
async def all_changer_not_accepted_invoices(call: CallbackQuery):
    user = await sync_to_async(TGUser.objects.get)(user_id=call.from_user.id)
    data = call.data.split("_")
    page = int(data[5]) if len(data) > 5 else 1
    per_page = 30
    offset = (page - 1) * per_page

    total = await count_changer_invoices(user)
    invoices = await get_changer_invoices(user, offset, per_page)

    if not invoices:
        await call.message.edit_text("No invoices found for this shop.")
        return

    builder = InlineKeyboardBuilder()
    for invoice in invoices:
        req_usage = await sync_to_async(ReqUsage.objects.filter)(usage_inv=invoice)
        active_not = ''
        if req_usage:
            req_usage = req_usage.first()
            if req_usage.active:
                active_not += "♻️"
            if req_usage.photo:
                active_not += "🖼"
        if invoice.accepted:
            active_not += "✅"
        else:
            active_not += "❌"
        builder.add(
            InlineKeyboardButton(text=f"{active_not}{invoice.date_used.strftime('%d.%m')}|+{invoice.amount_in_kzt}KZT",
                                 callback_data=f"changer_show_invoice_{invoice.id}"))
    builder.adjust(2)
    if page > 1:
        builder.add(InlineKeyboardButton(text="⬅️", callback_data=f"all_changer_not_accepted_invoices_{page - 1}"))
    if offset + per_page < total:
        builder.add(InlineKeyboardButton(text="➡️", callback_data=f"all_changer_not_accepted_invoices_{page + 1}"))
    builder.row(InlineKeyboardButton(text="< Назад", callback_data=f"all_changer_not_accepted_invoices"))

    await call.message.edit_reply_markup(reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("changer_show_invoice_"))
async def changer_show_invoice(call: CallbackQuery):
    data = call.data.split("_")
    invoice = await sync_to_async(Invoice.objects.get)(id=data[3])
    text = changer_invoice_text.format(operator=invoice.req.user.username if invoice.req.user.username else invoice.req.user.first_name,
                                       amount=round(invoice.amount_in_kzt, 2) if invoice.amount_in_kzt else 'уточняется',
                                     date=invoice.date_used.strftime('%d.%m.%Y %H:%M'), req=invoice.req.cart,
                                     amount_kgs=round(invoice.amount_in_fiat, 2) if invoice.amount_in_fiat else 'уточняется',
                                     amount_usdt=round(invoice.amount_in_usdt_for_changer, 2) if invoice.amount_in_usdt_for_changer else 'уточняется')
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Принять", callback_data=f"accept_invoice_{data[3]}"))
    builder.add(InlineKeyboardButton(text="Отказать", callback_data=f"decline_invoice_{data[3]}"))
    if invoice.status == "deleted" and not invoice.accepted:
        text += "\n❌ Инвойс удален"
    if invoice.accepted:
        text += "\n\nИНВОЙС ПОДТВЕРЖДЕН!"

    req_usages = await sync_to_async(lambda: ReqUsage.objects.filter(usage_inv=invoice, photo__isnull=False))()
    for req_usage in req_usages:
        if req_usage.photo:
            builder.add(InlineKeyboardButton(text="Фото Чека", callback_data=f"changer_show_photo_{req_usage.id}"))
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text=f"< Назад", callback_data="all_changer_not_accepted_invoices"))
    await call.message.edit_text(text=text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("changer_show_photo_"))
async def admin_show_photo(call: CallbackQuery):
    data = call.data.split("_")
    req_usage = await sync_to_async(ReqUsage.objects.get)(id=data[3])
    try:
        await call.message.answer_photo(req_usage.photo)
    except Exception as e:
        await call.message.answer_document(req_usage.photo)