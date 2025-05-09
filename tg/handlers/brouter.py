import asyncio
from aiogram import Bot, F, Router
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.filters import BaseFilter
from asgiref.sync import sync_to_async
from .utils import find_req, pay_checker, find_category_req
from ..models import TGUser, ShopOperator, OperatorClientChat, Course, Invoice, ReqUsage, Country, Req
from ..text import req_text
from datetime import timedelta
from django.utils import timezone

router = Router()


class IsKZT(BaseFilter):
    async def __call__(self, msg: Message):
        try:
            text = msg.text.lower()
            if text.endswith("t") or text.endswith("т"):
                user, created = await sync_to_async(TGUser.objects.get_or_create)(user_id=msg.from_user.id)
                shop_operator = await sync_to_async(ShopOperator.objects.filter)(operator=user, active=True)
                if shop_operator:
                    chat, created = await sync_to_async(OperatorClientChat.objects.get_or_create)(chat_id=msg.chat.id)
                    chat.operator = user
                    await sync_to_async(chat.save)()
                    amount = int(msg.text[:-1])
                    last_usage = await sync_to_async(
                        lambda: ReqUsage.objects.filter(chat=chat).order_by('-date_used').first())()
                    if last_usage:
                        if timezone.now() - last_usage.date_used > timedelta(minutes=10):
                            return True
                        else:
                            return False
                    else:
                        return True
                else:
                    return False
            else:
                return False
        except Exception as e:
            return False


class IsPhoto(BaseFilter):
    async def __call__(self, msg: Message):
        if msg.photo or msg.document:
            user, created = await sync_to_async(TGUser.objects.get_or_create)(user_id=msg.from_user.id)
            user.username = msg.from_user.username
            user.first_name = msg.from_user.first_name
            user.last_name = msg.from_user.last_name
            user.save()
            shop_operator = await sync_to_async(ShopOperator.objects.filter)(operator=user)
            if not shop_operator:
                chat, created = await sync_to_async(OperatorClientChat.objects.get_or_create)(chat_id=msg.chat.id)
                chat.client = user
                chat.save()
                last_usage = await sync_to_async(ReqUsage.objects.filter)(active=True, chat=chat)
                if last_usage:
                    return True
                else:
                    return False
            else:
                return False
        else:
            return False

@router.business_message(IsKZT())
async def kzt_answer(msg: Message, bot: Bot):
    amount = int(msg.text[:-1])
    chat = await sync_to_async(OperatorClientChat.objects.get)(chat_id=msg.chat.id)
    active_reqs = await sync_to_async(lambda: Req.objects.filter(active=True, archived=False))()
    builder = InlineKeyboardBuilder()
    if active_reqs.filter(kaspi=True).exists():
        builder.add(InlineKeyboardButton(text="💳 Kaspi", callback_data=f"choose_category_{amount}_kaspi"))
    if active_reqs.filter(bez_kaspi=True).exists():
        builder.add(InlineKeyboardButton(text="🛒 БезKaspi", callback_data=f"choose_category_{amount}_bezkaspi"))
    if active_reqs.filter(qiwi=True).exists():
        builder.add(InlineKeyboardButton(text="🐤 Qiwi", callback_data=f"choose_category_{amount}_qiwi"))
    if active_reqs.filter(terminal=True).exists():
        builder.add(InlineKeyboardButton(text="🏧 Terminal", callback_data=f"choose_category_{amount}_terminal"))
    builder.adjust(2)
    await msg.answer("Выберите категорию реквизита:", reply_markup=builder.as_markup())


@router.callback_query()
async def business_callbacks(call: CallbackQuery, bot: Bot):
    if call.data.startswith("choose_category_"):
        data = call.data.split("_")
        chat = await sync_to_async(OperatorClientChat.objects.get)(chat_id=call.chat.id)
        amount = int(data[2])
        category = data[3]
        last_usage = await sync_to_async(ReqUsage.objects.filter)(active=True, chat=chat)
        if last_usage:
            await call.answer("Завершите активную заявку.", show_alert=True)
            return
        else:
            req = await find_category_req(amount, category)
            if req:
                country = await sync_to_async(Country.objects.get)(id=req.country.id)
                shop_operator = await sync_to_async(ShopOperator.objects.filter)(operator=chat.operator, active=True)
                shop_operator = shop_operator.first()
                if country.country != "uzs":
                    fiat = amount / country.kzt_to_fiat
                    usdt_for_changer = fiat / country.fiat_to_usdt
                    usdt_for_shop = fiat / country.fiat_to_usdt_for_shop
                    new_invoice = await sync_to_async(Invoice.objects.create)(
                        req=req, amount_in_kzt=amount, amount_in_usdt=usdt_for_shop, amount_in_fiat=fiat,
                        amount_in_usdt_for_changer=usdt_for_changer, shop=shop_operator.shop,
                        shop_operator=shop_operator)
                    text = req_text.format(name=new_invoice.req.name, cart=new_invoice.req.cart, info=req.info if req.info else '!')
                    await call.message.answer(text, parse_mode="Markdown")
                    asyncio.create_task(pay_checker(new_invoice, call.message, bot, chat))
                elif country.country == "uzs":
                    fiat = amount * country.kzt_to_fiat
                    usdt_for_changer = fiat / country.fiat_to_usdt
                    usdt_for_shop = fiat / country.fiat_to_usdt_for_shop
                    new_invoice = await sync_to_async(Invoice.objects.create)(
                        req=req, amount_in_kzt=amount, amount_in_usdt=usdt_for_shop, amount_in_fiat=fiat,
                        amount_in_usdt_for_changer=usdt_for_changer)
                    text = req_text.format(name=new_invoice.req.name, cart=new_invoice.req.cart, info=req.info if req.info else '!')
                    await call.message.answer(text, parse_mode="Markdown")
                    asyncio.create_task(pay_checker(new_invoice, call.message, bot, chat))
            else:
                await call.answer("Реквизит уже занят, выберите другую категорию.", show_alert=True)


#
# @router.business_message(IsKZT())
# async def kzt_answer(msg: Message, bot: Bot):
#     amount = int(msg.text[:-1])
#     chat = await sync_to_async(OperatorClientChat.objects.get)(chat_id=msg.chat.id)
#     user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
#     shop_operator = await sync_to_async(ShopOperator.objects.filter)(operator=user, active=True)
#     shop_operator = shop_operator.first()
#     if chat:
#         course = await sync_to_async(Course.objects.first)()
#         amount_kzt_usd = amount / course.kzt_usd
#         req = await find_req(amount_kzt_usd)
#         if req:
#             country = await sync_to_async(Country.objects.get)(id=req.country.id)
#             if country.country != "uzs":
#                 fiat = amount / country.kzt_to_fiat
#                 usdt_for_changer = fiat / country.fiat_to_usdt
#                 usdt_for_shop = fiat / country.fiat_to_usdt_for_shop
#                 new_invoice = await sync_to_async(Invoice.objects.create)(
#                     req=req, amount_in_kzt=amount, amount_in_usdt=usdt_for_shop, amount_in_fiat=fiat,
#                     amount_in_usdt_for_changer=usdt_for_changer, shop=shop_operator.shop, shop_operator=shop_operator)
#                 text = req_text.format(name=new_invoice.req.name, cart=new_invoice.req.cart)
#                 if req.cart.startswith("9"):
#                     text += "\nПереводы только с Каспи\n"
#
#                 await msg.answer(text, parse_mode="Markdown")
#                 asyncio.create_task(pay_checker(new_invoice, msg, bot, chat))
#             elif country.country == "uzs":
#                 fiat = amount * country.kzt_to_fiat
#                 usdt_for_changer = fiat / country.fiat_to_usdt
#                 usdt_for_shop = fiat / country.fiat_to_usdt_for_shop
#                 new_invoice = await sync_to_async(Invoice.objects.create)(
#                     req=req, amount_in_kzt=amount, amount_in_usdt=usdt_for_shop, amount_in_fiat=fiat,
#                     amount_in_usdt_for_changer=usdt_for_changer)
#                 text = req_text.format(name=new_invoice.req.name, cart=new_invoice.req.cart)
#                 await msg.answer(text, parse_mode="Markdown")
#                 asyncio.create_task(pay_checker(new_invoice, msg, bot, chat))
#         else:
#             await msg.answer("no req")



@router.business_message(IsPhoto())
async def send_photo_to_op(msg: Message, bot: Bot):
    chat = await sync_to_async(OperatorClientChat.objects.get)(chat_id=msg.chat.id)
    last_usage = await sync_to_async(lambda: ReqUsage.objects.filter(chat=chat).order_by('-date_used').first())()
    req = last_usage.usage_req
    if last_usage:
        builder = InlineKeyboardBuilder()
        short_name = req.name[:3].upper()
        last_digits = req.cart[-4:] if req.cart and len(req.cart) >= 4 else "****"
        builder.add(InlineKeyboardButton(text=f"✅ ({last_usage.usage_inv.amount_in_kzt}T) {short_name} *{last_digits}", callback_data=f"accept_invoice_{last_usage.usage_inv.id}"))
        # builder.add(InlineKeyboardButton(text=f"✍️ Др сумма", callback_data=f"accept_and_change_fiat_{last_usage.usage_inv.id}"))
        builder.add(InlineKeyboardButton(text="❌", callback_data=f"decline_invoice_{last_usage.usage_inv.id}"))
        builder.adjust(1)
        if msg.photo:
            file_id = msg.photo[-1].file_id
            check_msg = await bot.send_photo(last_usage.usage_req.user.user_id, file_id, reply_markup=builder.as_markup())
        else:
            file_id = msg.document.file_id
            check_msg = await bot.send_document(last_usage.usage_req.user.user_id, file_id, reply_markup=builder.as_markup())
        last_usage.status = "photo_sent"
        last_usage.photo = file_id
        last_usage.save()
        try:
            await bot.pin_chat_message(chat_id=check_msg.chat.id, message_id=check_msg.message_id)
        except Exception as e:
            print(e)