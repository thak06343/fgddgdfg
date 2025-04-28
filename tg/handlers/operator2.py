from aiogram import F, Router, Bot
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Filter
from asgiref.sync import sync_to_async
from django.utils import timezone
from .utils import PAGE_SIZE, find_req
from ..kb import shop_operator_panel
from ..models import TGUser, Invoice, Req, ShopOperator, ReqUsage, Shop, Course, OperatorMode
from ..text import order_operator_text
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
    shop_operator = shop_operator.first()
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Все Инвойсы", callback_data="shop_operator_all_invoices"))
    await msg.answer(f"`{shop_operator.shop.name.upper()}`", reply_markup=builder.as_markup())

@sync_to_async
def get_invoices_for_operator(operator, offset, limit):
    return list(Invoice.objects.filter(shop_operator=operator).order_by('-date_used')[offset:offset + limit])

@sync_to_async
def count_invoices_for_operator(operator):
    return Invoice.objects.filter(shop_operator=operator).count()

@router.callback_query(F.data.startswith("shop_operator_all_invoices"))
async def shop_operator_all_invoices(call: CallbackQuery):
    data = call.data.split("_")
    page = int(data[4]) if len(data) > 4 else 1
    per_page = 30
    offset = (page - 1) * per_page

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
        if invoice.accepted:
            active_not += "✅"
        else:
            active_not += "❌"
        builder.add(InlineKeyboardButton(text=f"{active_not}{invoice.date_used.strftime('%d.%m')}|+{invoice.amount_in_kzt}KZT", callback_data=f"shop_operator_invoice_{invoice.id}"))
    builder.adjust(2)
    if page > 1:
        builder.add(InlineKeyboardButton(text="⬅️",callback_data=f"shop_operator_all_invoices_{page - 1}"))
    if offset + per_page < total:
        builder.add(InlineKeyboardButton(text="➡️",callback_data=f"shop_operator_all_invoices_{page + 1}"))
    builder.row(InlineKeyboardButton(text="< Назад", callback_data=f"back_to_shop_operator_invoices"))
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
            builder.adjust(1)
            builder.row(InlineKeyboardButton(text="< Назад", callback_data="shop_operator_all_invoices"))
            await call.message.edit_text(text, reply_markup=builder.as_markup())
        except Exception as e:
            print(e)

class OperatorModeState(StatesGroup):
    awaiting_amount = State()
    in_mode = State()

@router.message(F.text == "🕹 Режим платежей")
async def shop_operator_mode(msg: Message, state: FSMContext):
    usdt_amount = 200
    req = await find_req(usdt_amount)
    if not req:
        usdt_amount = 100
        req = await find_req(usdt_amount)
    if req:
        text = f"Реквизиты меняются каждые ${usdt_amount}\n❗️ Не выходите из режима пока не отправите все чеки!\n\n🟢 Режим активирован, ожидаются чеки..\n\n"
        text2 = (f"{req.name}\n"
                 f"{req.country.flag} {req.cart}")


        shop_operator_bottoms = ReplyKeyboardMarkup(resize_keyboard=True,
                                                    keyboard=[
                                                        [KeyboardButton(text="Выйти из режима")],
                                                    ])
        user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
        shop_operator = await sync_to_async(ShopOperator.objects.filter)(operator=user, active=True)
        if shop_operator:
            shop_operator = shop_operator.first()
            new_operator_mode = await sync_to_async(OperatorMode.objects.create)(req=req, max_amount=usdt_amount)
            await state.update_data(mode_id=new_operator_mode.id, shop_id=shop_operator.shop.id, req_id=req.id)
            await state.set_state(OperatorModeState.in_mode)
            await msg.answer(text, reply_markup=shop_operator_bottoms)
            await msg.answer(text2)
        else:
            shop = await sync_to_async(Shop.objects.filter)(boss=user)
            if shop:
                shop = shop.first()
                new_operator_mode = await sync_to_async(OperatorMode.objects.create)(req=req, max_amount=usdt_amount)
                await state.update_data(mode_id=new_operator_mode.id, shop_id=shop.id, req_id=req.id)
                await state.set_state(OperatorModeState.in_mode)
                await msg.answer(text, reply_markup=shop_operator_bottoms)
                await msg.answer(text2)
    else:
        await msg.answer("no req")


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

            builder.add(InlineKeyboardButton(text=f"✅ {short_name} *{last_digits}",
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
