from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Filter
from asgiref.sync import sync_to_async
from django.utils import timezone
from .utils import shop_balance, get_ltc_usd_rate, transfer_to_shop, PAGE_SIZE, operator_invoices, IsLtcReq
from ..kb import changer_panel_bottom, shop_panel
from ..models import TGUser, Invoice, Country, Req, WithdrawalMode, Shop, Promo, ShopOperator, ReqUsage
from ..text import main_page_text, add_new_req_text, settings_text, order_operator_text
from django.db.models import Sum, Count, Q, FloatField
from django.db.models.functions import Coalesce
from datetime import date
router = Router()

class IsShopBoss(Filter):
    async def __call__(self, msg: Message):
        try:
            user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
            shop = await sync_to_async(Shop.objects.filter)(boss=user)
            if shop:
                return True
        except Exception as e:
            return False

router.message.filter(IsShopBoss())

@router.message(F.text == "💎 Главное")
async def shop_main(msg: Message):
    user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
    shop = await sync_to_async(Shop.objects.get)(boss=user)
    balance, invoices = await shop_balance(shop)
    text = f"💰 *Баланс:* *${round(balance, 2)}*\n"
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=f"⚡️ 𝑳𝑻𝑪 ({shop.prc}%)", callback_data=f"shop_order_to_withdraw"))
    await msg.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

class WithdrawToShopState(StatesGroup):
    awaiting_ltc_req = State()

@router.callback_query(F.data == "shop_order_to_withdraw")
async def shop_order_to_withdraw(call: CallbackQuery, state: FSMContext):
    user = await sync_to_async(TGUser.objects.get)(user_id=call.from_user.id)
    shop = await sync_to_async(Shop.objects.get)(boss=user)
    balance, invoices = await shop_balance(shop)
    if balance >= 50:
        await state.set_state(WithdrawToShopState.awaiting_ltc_req)
        await call.message.answer("💸 Введите кошелек LTC для вывода:")
    else:
        await call.answer("Недостаточный баланс! Вывод от 50$", show_alert=True)

@router.message(WithdrawToShopState.awaiting_ltc_req)
async def awaiting_ltc_to_send_shop(msg: Message, state: FSMContext):
    user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
    shop = await sync_to_async(Shop.objects.get)(boss=user)
    try:
        ltc_address = msg.text.strip()
        is_ltc_req = await IsLtcReq(ltc_address)
        if is_ltc_req:
            await state.clear()
            balance, invoices = await shop_balance(shop)
            current_prc = 100 - shop.prc
            balance = balance / 100 * current_prc
            try:
                ltc_usdt_price = await get_ltc_usd_rate()
            except Exception as e:
                await msg.answer(f"❌ Не удалось получить курс LTC. Попробуйте позже.\n{e}")
                return
            ltc_amount = balance / ltc_usdt_price
            amount_in_satoshi = int(ltc_amount * 100_000_000)
            pack = await sync_to_async(WithdrawalMode.objects.create)(user=user, active=True, requisite=ltc_address,
                                                                      ltc_amount=ltc_amount)
            await sync_to_async(pack.invoices.add)(*invoices)
            result = await transfer_to_shop(amount_in_satoshi, ltc_address, pack.id)
            await msg.answer(result, parse_mode="Markdown")
        else:
            await msg.answer("Неверный LTC адрес, попробуйте еще раз")
    except Exception as e:
        print(e)

class NewShopState(StatesGroup):
    awaiting_title = State()

@router.callback_query(F.data == "adding_new_shop")
async def adding_new_shop(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Пожалуйста введите название вашего бизнеса:")
    await state.set_state(NewShopState.awaiting_title)

@router.message(NewShopState.awaiting_title)
async def awaiting_shop_tittle(msg: Message, state: FSMContext):
    if msg.text:
        user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
        new_shop, created = await sync_to_async(Shop.objects.get_or_create)(boss=user)
        new_shop.name = msg.text
        new_shop.save()
        bottom = await shop_panel()
        await state.clear()
        await msg.answer(f"{msg.text.upper()} создан!", reply_markup=bottom)
    else:
        await msg.answer("Как сохранить вас в системе? Введите текст:")

@router.message(F.text == "🔗 Статистика")
async def shop_statistics(msg: Message):
    user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
    shop = await sync_to_async(Shop.objects.get)(boss=user)
    today = date.today()

    total_amount_usdt_today = await sync_to_async(lambda: Invoice.objects.filter(accepted=True,shop=shop,date_used__date=today).
                                                  aggregate(total=Coalesce(Sum('amount_in_usdt'), 0, output_field=FloatField()))['total'])()
    invoices_count_today = await sync_to_async(lambda: Invoice.objects.filter(accepted=True, shop=shop, date_used__date=today).count())()
    total_amount_usdt_all = await sync_to_async(lambda: Invoice.objects.filter(accepted=True, shop=shop).aggregate
                        (total=Coalesce(Sum('amount_in_usdt'), 0, output_field=FloatField()))['total'])()
    invoices_count_all = await sync_to_async(lambda: Invoice.objects.filter(accepted=True,shop=shop).count())()


    stat_text = (
        f"📊 <b>Статистика магазина</b>\n\n"
        f"🔹 <b>Сегодня ({today.strftime('%d.%m.%Y')}):</b>\n"
        f" • Количество оплат: <b>{invoices_count_today}</b>\n"
        f" • Сумма в USDT: <b>{round(total_amount_usdt_today, 2)}</b> $\n\n"
        f"🔹 <b>Всего:</b>\n"
        f" • Количество оплат: <b>{invoices_count_all}</b>\n"
        f" • Сумма в USDT: <b>{round(total_amount_usdt_all, 2)}</b> $\n"
    )

    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="💳 Платежи", callback_data="all_shop_invoices"))
    builder.add(InlineKeyboardButton(text=f"Операторы", callback_data="all_shop_operators"))
    builder.adjust(1)
    await msg.answer(stat_text, reply_markup=builder.as_markup(), parse_mode="HTML")

@sync_to_async
def get_invoices_for_shop(shop, offset, limit):
    return list(Invoice.objects.filter(shop=shop).order_by('-date_used')[offset:offset + limit])

@sync_to_async
def count_invoices_for_shop(shop):
    return Invoice.objects.filter(shop=shop).count()

@router.callback_query(F.data == "all_shop_invoices")
async def all_shop_invoices(call: CallbackQuery):
    user = await sync_to_async(TGUser.objects.get)(user_id=call.from_user.id)
    shop = await sync_to_async(Shop.objects.get)(boss=user)
    data = call.data.split("_")
    page = int(data[3]) if len(data) > 3 else 1
    per_page = 30
    offset = (page - 1) * per_page
    total = await count_invoices_for_shop(shop)
    invoices = await get_invoices_for_shop(shop, offset, per_page)
    if not invoices:
        await call.message.answer("Нет инвойсов.")
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
        builder.add(InlineKeyboardButton(
            text=f"{active_not}{invoice.date_used.strftime('%d.%m')}|+{invoice.amount_in_kzt}KZT",
            callback_data=f"shop_boss_invoice_{invoice.id}"))

    if page > 1:
        builder.add(InlineKeyboardButton(text="⬅️", callback_data=f"all_shop_invoices_{page - 1}"))
    if offset + per_page < total:
        builder.add(InlineKeyboardButton(text="➡️", callback_data=f"all_shop_invoices_{page + 1}"))
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="< Назад", callback_data=f"business_back_to_stats"))
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())

@router.callback_query(F.data == "business_back_to_stats")
async def business_back_to_stats(call: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="💳 Платежи", callback_data="all_shop_invoices"))
    builder.add(InlineKeyboardButton(text=f"Операторы", callback_data="all_shop_operators"))
    builder.adjust(1)
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("shop_boss_invoice_"))
async def shop_boss_invoice(call: CallbackQuery):
    data = call.data.split("_")
    invoice = await sync_to_async(Invoice.objects.get)(id=data[3])
    req_usage = await sync_to_async(ReqUsage.objects.filter)(usage_inv=invoice)
    if req_usage:
        req_usage = req_usage.first()
        if req_usage and req_usage.chat and req_usage.chat.client:
            full_name = req_usage.chat.client.first_name if req_usage.chat.client.first_name else ''
            full_name += req_usage.chat.client.last_name if req_usage.chat.client.last_name else ''
            if req_usage.chat.client.username:
                user_link = f"@{req_usage.chat.client.username}"
            else:
                user_link = f"tg://user?id={req_usage.chat.client.user_id}"
        else:
            full_name = "Неизвестный пользователь"
            user_link = "Нет ссылки"
        date_text = timezone.now().strftime('%d.%m.%Y %H:%M')
        text = order_operator_text.format(user_link=user_link, amount=invoice.amount_in_kzt, date=date_text,
                                          full_name=full_name, status=req_usage.status)
        builder = InlineKeyboardBuilder()
        if req_usage.active:
            builder.add(
                InlineKeyboardButton(text=f"Не получается отправить", callback_data=f"cant_send_{invoice.req.id}"))
        builder.adjust(1)
        builder.row(InlineKeyboardButton(text="< Назад", callback_data="all_shop_invoices"))
        await call.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    else:
        await call.answer("Нет данных!")

@router.message(F.text == "⚙️ Настройки")
async def shop_settings(msg: Message):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=f"➕ Оператор", callback_data=f"add_new_shop_operator"))
    builder.adjust(1, 2)
    await msg.answer(settings_text, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("operator_"))
async def operator_manage(call: CallbackQuery):
    data = call.data.split("_")
    operator_id = data[1]
    operator = await sync_to_async(ShopOperator.objects.get)(id=operator_id)
    if operator.active:
        operator.active = False
        await call.answer(f"Оператор больше не в строю", show_alert=True)
    elif not operator.active:
        operator.active = True
        await call.answer(f"Оператор снова в строю", show_alert=True)
    operator.save()
    user = await sync_to_async(TGUser.objects.get)(user_id=call.from_user.id)
    shop = await sync_to_async(Shop.objects.get)(boss=user)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"➕ Оператор", callback_data=f"add_new_shop_operator"))
    operators = await sync_to_async(ShopOperator.objects.filter)(shop=shop)
    for operator in operators:
        text = f"{'🟢' if operator.active else '⚫️'} {operator.operator.username if operator.operator.username else operator.operator.first_name}"
        builder.add(InlineKeyboardButton(
            text=text, callback_data=f"operator_{operator.id}"))
    builder.adjust(1, 2)
    await call.message.edit_text(settings_text, reply_markup=builder.as_markup())




@router.callback_query(F.data == "all_shop_operators")
async def my_operators(call: CallbackQuery):
    user = await sync_to_async(TGUser.objects.get)(user_id=call.from_user.id)
    shop = await sync_to_async(Shop.objects.get)(boss=user)
    builder = InlineKeyboardBuilder()
    operators = await sync_to_async(ShopOperator.objects.filter)(shop=shop)
    builder.row(InlineKeyboardButton(text="🔱 Все инвойсы", callback_data="business_all_invoices"))
    text = " "
    for operator in operators:
        balance, invoices = await operator_invoices(operator.operator)
        text += (f"{operator.username if operator.username else f'{operator.first_name} {operator.last_name}'}\n"
                 f"За все время: {round(balance, 2)} (кол-во: {len(invoices)})\n\n")
        builder.add(InlineKeyboardButton(text=f"{operator.username if operator.username else operator.first_name}", callback_data=f"business_op_invoices_{operator.id}"))
    builder.adjust(2)
    if not text:
        text = "Нет операторов"
    await call.message.edit_text(text, reply_markup=builder.as_markup())

@router.callback_query(F.data == "add_new_shop_operator")
async def add_new_shop_oper(call: CallbackQuery, bot: Bot):
    user = await sync_to_async(TGUser.objects.get)(user_id=call.from_user.id)
    shop = await sync_to_async(Shop.objects.get)(boss=user)
    new_operator_promo = await sync_to_async(Promo.objects.create)(type="new_shop_operator", shop=shop)
    bot_info = await bot.get_me()
    bot_user = bot_info.username
    link = f"https://t.me/{bot_user}?start={new_operator_promo.code}"
    await call.message.answer(f"💡 Отправьте ссылку вашему новому оператору.\n\n`{link}`", parse_mode="Markdown")

@sync_to_async
def get_invoices_for_shop_operator(shop_operator, offset, limit):
    return list(Invoice.objects.filter(shop_operator=shop_operator).order_by('-date_used')[offset:offset + limit])

@sync_to_async
def count_invoices_for_shop_operator(shop_operator):
    return Invoice.objects.filter(shop_operator=shop_operator).count()

@router.callback_query(F.data.startswith("business_op_invoices_"))
async def business_op_invoices(call: CallbackQuery):
    data = call.data.split("_")
    operator = await sync_to_async(TGUser.objects.get)(id=data[3])
    data = call.data.split("_")
    page = int(data[3]) if len(data) > 3 else 1
    per_page = 30
    offset = (page - 1) * per_page

    total = await get_invoices_for_shop_operator(operator, offset, per_page)
    invoices = await count_invoices_for_shop_operator(operator)

    if not invoices:
        await call.message.answer("Нет инвойсов.")
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
        builder.add(InlineKeyboardButton(
            text=f"{active_not}{invoice.date_used.strftime('%d.%m')}|+{invoice.amount_in_kzt}KZT",
            callback_data=f"shop_boss_invoice_{invoice.id}"))

    if page > 1:
        builder.add(InlineKeyboardButton(text="⬅️", callback_data=f"business_op_invoices_{page - 1}"))
    if offset + per_page < total:
        builder.add(InlineKeyboardButton(text="➡️", callback_data=f"business_op_invoices_{page + 1}"))
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="< Назад", callback_data=f"business_back_to_stats"))
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())
