from aiogram import  F, Router
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Filter
from asgiref.sync import sync_to_async
from django.utils import timezone
from .utils import PAGE_SIZE
from ..models import TGUser, Invoice, Req, ShopOperator, ReqUsage, Shop
from ..text import order_operator_text
from datetime import  date

router = Router()

class IsOperFilter(Filter):
    async def __call__(self, msg: Message):
        try:
            user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
            shop_operator = await sync_to_async(ShopOperator.objects.filter)(operator=user, active=True)
            if shop_operator:
                return True
            else:
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


@router.callback_query(F.data == "shop_operator_all_invoices")
async def shop_operator_all_invoices(call: CallbackQuery):
    user = await sync_to_async(TGUser.objects.get)(user_id=call.from_user.id)
    shop_operator = await sync_to_async(ShopOperator.objects.get)(operator=user)
    invoices = await sync_to_async(lambda: Invoice.objects.filter(requsage__chat__operator=user).distinct().order_by('-date_used'))()
    if invoices:
        total_pages = (len(invoices) + PAGE_SIZE - 1) // PAGE_SIZE
        page_number = 1

        @router.callback_query(F.data.startswith("next_page_"))
        async def next_page(call: CallbackQuery):
            page_number = int(call.data.split("_")[2]) + 1
            if page_number > total_pages:
                page_number = total_pages
            await send_invoices_page(call, page_number, total_pages)

        @router.callback_query(F.data.startswith("prev_page_"))
        async def next_page(call: CallbackQuery):
            page_number = int(call.data.split("_")[2]) - 1
            if page_number > 1:
                page_number = 1
            await send_invoices_page(call, page_number, total_pages)

        async def send_invoices_page(call, page_number, total_pages):
            start_index = (page_number - 1) * PAGE_SIZE
            end_index = min(start_index + PAGE_SIZE, len(invoices))
            inv_page = invoices[start_index:end_index]

            builder = InlineKeyboardBuilder()
            for invoice in inv_page:
                active_not = ''
                if invoice.accepted:
                    active_not += "✅"
                else:
                    active_not += "♻️"
                builder.add(InlineKeyboardButton(text=f"{active_not}{invoice.date_used.strftime('%d.%m')}|+{invoice.amount_in_kzt}KZT", callback_data=f"shop_operator_invoice_{invoice.id}"))
            builder.adjust(2)
            if page_number > 1:
                builder.row(InlineKeyboardButton(text=f"< Предыдущая страница", callback_data=f"prev_page_{page_number - 1}"))
            if page_number < total_pages:
                builder.row(InlineKeyboardButton(text=f"> Следующая страница", callback_data=f"next_page_{page_number + 1}"))
            await call.message.edit_text(f"`{shop_operator.shop.name}`", reply_markup=builder.as_markup())
        await send_invoices_page(call, page_number, total_pages)
    else:
        await call.message.answer("Нет инвойсов!")



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
        req_usage = req_usage.first()
        full_name = req_usage.chat.client.first_name if req_usage.chat.client.first_name else ''
        full_name += req_usage.chat.client.last_name if req_usage.chat.client.last_name else ''
        if req_usage.chat.client.username:
            user_link = f"@{req_usage.chat.client.username}"
        else:
            user_link = f"tg://user?id={req_usage.chat.client.user_id}"
        date_text = timezone.now().strftime('%d.%m.%Y %H:%M')
        text = order_operator_text.format(user_link=user_link, amount=invoice.amount_in_kzt, date=date_text, full_name=full_name)
        builder = InlineKeyboardBuilder()
        if req_usage.active:
            builder.add(InlineKeyboardButton(text=f"Не получается отправить", callback_data=f"cant_send_{invoice.id}"))
        builder.adjust(1)
        builder.row(InlineKeyboardButton(text="< Назад", callback_data="shop_operator_all_invoices"))
        await call.message.edit_text(text, reply_markup=builder.as_markup())