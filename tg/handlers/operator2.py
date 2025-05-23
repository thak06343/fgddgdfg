import asyncio

from aiogram import F, Router, Bot
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Filter
from asgiref.sync import sync_to_async
from django.template.defaultfilters import default
from django.utils import timezone

from .callback import InvoicePagination
from .utils import PAGE_SIZE, find_req, get_req_with_fallback, format_req_info, accept_checker_in_mode
from ..kb import shop_operator_panel
from ..models import TGUser, Invoice, Req, ShopOperator, ReqUsage, Shop, Course, OperatorMode
from ..text import order_operator_text, mode_text
from datetime import  date
from aiogram.fsm.context import FSMContext
router = Router()

class IsOperFilter(Filter):
    async def __call__(self, msg: Message):
        try:
            user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
            shop_operator = await sync_to_async(ShopOperator.objects.filter)(operator=user, active=True)
            if shop_operator:
                return True
            else:
                shop = await sync_to_async(Shop.objects.filter)(boss=user)
                if shop:
                    return True
                return False
        except Exception as e:
            return False

router.message.filter(IsOperFilter())

@router.message(F.text == "🔱 Инвойсы")
async def shop_operator_invoices(msg: Message):
    user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
    shop_operator = await sync_to_async(ShopOperator.objects.filter)(operator=user)
    if shop_operator:
        shop_operator = shop_operator.first()
        shop = shop_operator.shop
    else:
        shop = await sync_to_async(Shop.objects.filter)(boss=user)
        if shop:
            shop = shop.first()
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Все Инвойсы", callback_data="shop_operator_all_invoices"))
    await msg.answer(f"`{shop.name.upper() if shop.name else 'Магазин'}`", reply_markup=builder.as_markup(), parse_mode="Markdown")

@sync_to_async
def get_invoices_for_operator(operator, offset, limit):
    return list(Invoice.objects.filter(shop_operator=operator).order_by('-date_used')[offset:offset + limit])

@sync_to_async
def count_invoices_for_operator(operator):
    return Invoice.objects.filter(shop_operator=operator).count()


@router.callback_query(InvoicePagination.filter())
async def shop_operator_all_invoices(call: CallbackQuery, callback_data: InvoicePagination):
    page = callback_data.page
    per_page = 30
    offset = page * per_page

    user = await sync_to_async(TGUser.objects.get)(user_id=call.from_user.id)
    shop_operator = await sync_to_async(ShopOperator.objects.get)(operator=user)

    total = await count_invoices_for_operator(shop_operator)
    invoices = await get_invoices_for_operator(shop_operator, offset, per_page)

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
        active_not += "✅" if invoice.accepted else "❌"

        builder.button(text=f"{active_not}{invoice.date_used.strftime('%d.%m')}|+{invoice.amount_in_kzt}KZT",
                       callback_data=f"shop_operator_invoice_{invoice.id}")
    builder.adjust(2)
    if page > 0:
        builder.button(text="⬅️", callback_data=InvoicePagination(page=page - 1))
    if offset + per_page < total:
        builder.button(text="➡️", callback_data=InvoicePagination(page=page + 1))

    builder.row(InlineKeyboardButton(text="< Назад", callback_data="back_to_shop_operator_invoices"))

    await call.message.edit_reply_markup(reply_markup=builder.as_markup())


@router.callback_query(F.data == "back_to_shop_operator_invoices")
async def back_to_shop_operator_invoices(call: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Все Инвойсы", callback_data="shop_operator_all_invoices"))
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("cant_send_"))
async def cant_send_req(call: CallbackQuery):
    data = call.data.split("_")
    today = date.today()
    invoice = await sync_to_async(Invoice.objects.get)(id=data[2])
    req = invoice.req
    req_usage, created = await sync_to_async(ReqUsage.objects.get_or_create)(usage_req=req, status="cant_send", active=False, usage_inv=invoice)
    cant_sends = await sync_to_async(ReqUsage.objects.filter)(usage_req=req, status="cant_send", active=False, date_used__date=today)
    if len(cant_sends) >= 3:
        req.archived = True
        await sync_to_async(req.save)()
    await call.answer("Информация отправлена!", show_alert=True)

@router.callback_query(F.data.startswith("shop_operator_invoice_"))
async def shop_operator_invoice(call: CallbackQuery):
    data = call.data.split("_")
    invoice = await sync_to_async(Invoice.objects.get)(id=data[3])
    req_usage = await sync_to_async(ReqUsage.objects.filter)(usage_inv=invoice)
    if req_usage:
        try:
            req_usage = req_usage.first()
            full_name = req_usage.chat.client.first_name if req_usage.chat.client.first_name else ' '
            full_name += req_usage.chat.client.last_name if req_usage.chat.client.last_name else ' '
            if req_usage.chat.client.username:
                user_link = f"@{req_usage.chat.client.username}"
            else:
                user_link = f"tg://user?id={req_usage.chat.client.user_id}"
            date_text = timezone.now().strftime('%d.%m.%Y %H:%M')
            status = req_usage.status
            text = order_operator_text.format(user_link=user_link, amount=invoice.amount_in_kzt, date=date_text, full_name=full_name, status=status)
            if invoice.accepted:
                text += "\n✔️ Платеж принят!"
            builder = InlineKeyboardBuilder()
            if req_usage.active:
                builder.add(InlineKeyboardButton(text=f"Не получается отправить", callback_data=f"cant_send_{invoice.id}"))
            if req_usage.photo:
                builder.add(InlineKeyboardButton(text="Отправить фото", callback_data=f"send_photo_operator_{req_usage.id}"))
            builder.adjust(1)
            builder.row(InlineKeyboardButton(text="< Назад", callback_data="shop_operator_all_invoices"))
            await call.message.edit_text(text, reply_markup=builder.as_markup())
        except Exception as e:
            print(e)
    else:
        await call.answer("Нет данных о платеже.")

@router.callback_query(F.data.startswith("send_photo_operator_"))
async def send_photo_operator(call: CallbackQuery):
    data = call.data.split("_")
    req_usage = await sync_to_async(ReqUsage.objects.get)(id=data[3])
    try:
        await call.message.answer_photo(req_usage.photo)
    except Exception as e:
        await call.message.answer_document(req_usage.photo)

class OperatorModeState(StatesGroup):
    awaiting_amount = State()
    in_mode = State()

@router.message(F.text == "🕹 Режим платежей")
async def shop_operator_mode(msg: Message, state: FSMContext):
    try:
        user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
        shop_operator = await sync_to_async(ShopOperator.objects.filter)(operator=user, active=True)
        if shop_operator:
            shop_operator = shop_operator.first()
            shop = shop_operator.shop
        else:
            shop = await sync_to_async(Shop.objects.filter)(boss=user)
            shop = shop.first()
    except Exception as e:
        print(e)
        shop = None
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔄 Создать новое обращение", callback_data="create_new_mode"))
    if shop:
        last_mode_usages = await sync_to_async(OperatorMode.objects.filter)(shop=shop)
        if last_mode_usages:
            last_mode_usages = last_mode_usages[:2]
            for i in last_mode_usages:
                short_name = i.req.name[:3].upper()
                builder.add(InlineKeyboardButton(text=f"{short_name} *{i.req.cart[-4:]}", callback_data=f"old_mode_{i.id}"))
    builder.adjust(1)
    await msg.answer(mode_text, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("old_mode_"))
async def old_mode(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    op_mode = await sync_to_async(OperatorMode.objects.get)(id=data[2])
    req = op_mode.req
    text = f"Отправлять только случайно не отправленные чеки, для работы создайте новый режим.\n\n🟢 Режим активирован, ожидаются чеки..\n\n"
    text2 = (f"{req.name}\n"
             f"{req.country.flag} {req.cart}")

    shop_operator_bottoms = ReplyKeyboardMarkup(resize_keyboard=True,
                                                keyboard=[
                                                    [KeyboardButton(text="Выйти из режима")],
                                                ])
    user = await sync_to_async(TGUser.objects.get)(user_id=call.from_user.id)
    shop_operator = await sync_to_async(ShopOperator.objects.filter)(operator=user, active=True)
    if shop_operator:
        shop_operator = shop_operator.first()
        await state.update_data(mode_id=op_mode.id, shop_id=shop_operator.shop.id, req_id=req.id)
        await state.set_state(OperatorModeState.in_mode)
        await call.message.answer(text, reply_markup=shop_operator_bottoms)
        await call.message.answer(text2)
    else:
        shop = await sync_to_async(Shop.objects.filter)(boss=user)
        if shop:
            shop = shop.first()
            await state.update_data(mode_id=op_mode.id, shop_id=shop.id, req_id=req.id)
            await state.set_state(OperatorModeState.in_mode)
            await call.message.answer(text, reply_markup=shop_operator_bottoms)
            await call.message.answer(text2)

@router.callback_query(F.data == "create_new_mode")
async def create_new_mode(call: CallbackQuery, state: FSMContext):
    req, usdt_amount = await get_req_with_fallback()
    if not req:
        await call.message.answer("no req")
        return

    text = (
        f"Реквизиты меняются каждые ${usdt_amount}\n"
        f"❗️ Не выходите из режима пока не отправите все чеки!\n\n"
        f"🟢 Режим активирован, ожидаются чеки..\n\n"
    )
    text2 = format_req_info(req)

    other_reqs_qs = await sync_to_async(Req.objects.filter)(user=req.user, active=True, archived=False)
    other_reqs = [r for r in other_reqs_qs if r.id != req.id]

    categories = {'kaspi': None,'bez_kaspi': None,'qiwi': None,'terminal': None}

    for r in other_reqs:
        if r.kaspi and not categories['kaspi']:
            categories['kaspi'] = r
        if r.bez_kaspi and not categories['bez_kaspi']:
            categories['bez_kaspi'] = r
        if r.qiwi and not categories['qiwi']:
            categories['qiwi'] = r
        if r.terminal and not categories['terminal']:
            categories['terminal'] = r

    filtered_reqs = [r for r in categories.values() if r]
    if filtered_reqs:
        text2 += "\n🔁 Дополнительные реквизиты:\n"
        for r in filtered_reqs:
            text2 += "\n" + format_req_info(r)

    shop_operator_bottoms = ReplyKeyboardMarkup(resize_keyboard=True,
                                                keyboard=[[KeyboardButton(text="Выйти из режима")]])

    user = await sync_to_async(TGUser.objects.get)(user_id=call.from_user.id)
    shop_operator_qs = await sync_to_async(ShopOperator.objects.filter)(operator=user, active=True)
    shop = None

    if shop_operator_qs:
        shop_operator = shop_operator_qs.first()
        shop = shop_operator.shop
    else:
        shop_qs = await sync_to_async(Shop.objects.filter)(boss=user)
        if shop_qs:
            shop = shop_qs.first()
    if shop:
        new_operator_mode = await sync_to_async(OperatorMode.objects.create)(req=req, max_amount=usdt_amount, shop=shop)
        await state.update_data(mode_id=new_operator_mode.id,shop_id=shop.id,req_id=req.id,)
        await state.set_state(OperatorModeState.in_mode)
        await call.message.answer(text, reply_markup=shop_operator_bottoms)
        await call.message.answer(text2)



@router.message(OperatorModeState.in_mode)
async def in_mode(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    req_id = data.get("req_id")
    mode_id = data.get("mode_id")
    shop_id = data.get("shop_id")
    req = await sync_to_async(Req.objects.get)(id=int(req_id))
    shop = await sync_to_async(Shop.objects.get)(id=int(shop_id))
    operator_mode = await sync_to_async(OperatorMode.objects.get)(id=int(mode_id))
    if msg.text == "Выйти из режима":
        await state.clear()
        shop_operator_markup = await shop_operator_panel()
        operator_mode.active = False
        operator_mode.save()
        await msg.answer("Вы вышли из режима", reply_markup=shop_operator_markup)
    else:
        if msg.photo or msg.document:
            builder = InlineKeyboardBuilder()
            short_name = req.name[:3].upper()
            last_digits = req.cart[-4:] if req.cart and len(req.cart) >= 4 else "****"
            new_invoice = await sync_to_async(Invoice.objects.create)(req=req, shop=shop)

            check_msg = await msg.reply("♻️ На обработке")

            builder.add(InlineKeyboardButton(text=f"Указать сумму {short_name} *{last_digits}",
                                             callback_data=f"in_mode_accept_{new_invoice.id}_{check_msg.chat.id}_{check_msg.message_id}_{operator_mode.id}"))
            builder.add(InlineKeyboardButton(text="❌", callback_data=f"decline_invoice_{new_invoice.id}"))
            builder.adjust(1)

            if msg.photo:
                file_id = msg.photo[-1].file_id
                await bot.send_photo(chat_id=req.user.user_id, photo=file_id,reply_markup=builder.as_markup())
            else:
                try:
                    file_id = msg.document.file_id
                    await bot.send_document(chat_id=req.user.user_id, document=file_id,reply_markup=builder.as_markup())
                except Exception as e:
                    file_id = None
            new_usage = await sync_to_async(ReqUsage.objects.create)(usage_inv=new_invoice,
                                                                     status="in_operator_mode", usage_req=req,
                                                                     photo=file_id)
            asyncio.create_task(accept_checker_in_mode(check_msg, new_usage))
