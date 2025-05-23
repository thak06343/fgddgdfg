import asyncio

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandObject, BaseFilter
from asgiref.sync import sync_to_async

from .operator import main_page
from ..kb import changer_panel_bottom, shop_panel, shop_operator_panel, admin_panel
from ..models import TGUser, Promo, WithdrawalMode, Shop, ShopOperator
from .utils import promo_coder


router = Router()

class HasActiveInvoiceFilter(BaseFilter):
    async def __call__(self, msg: Message) -> bool:
        user_id = msg.from_user.id

        user, created = await sync_to_async(TGUser.objects.get_or_create)(user_id=user_id)
        user.username = msg.from_user.username
        user.first_name = msg.from_user.first_name
        user.last_name = msg.from_user.last_name
        user.save()
        if not user:

            return False

        return await sync_to_async(WithdrawalMode.objects.filter(user=user, active=True).exists)()

@router.message(HasActiveInvoiceFilter())
async def send_invoice_reminder(msg: Message):
    user_id = msg.from_user.id
    user = await sync_to_async(lambda: TGUser.objects.get(user_id=user_id))()
    mode = await sync_to_async(lambda: WithdrawalMode.objects.filter(user=user, active=True).prefetch_related('invoices').first())()


    ltc_address = mode.requisite
    ltc_amount = mode.ltc_amount

    text = (f"🧾 <b>Ваш активный счёт на оплату</b>\n\n"
        f"🪙 Сумма в LTC: <b>{ltc_amount} LTC</b>\n\n"
        f"📬 LTC-адрес для оплаты:\n<code>{ltc_address}</code>\n")

    await msg.answer(text, parse_mode="HTML")

@router.message(Command("start"))
async def start(msg: Message, command: CommandObject, bot: Bot, state: FSMContext):
    user, created = await sync_to_async(TGUser.objects.get_or_create)(user_id=msg.from_user.id)
    user.first_name = msg.from_user.first_name
    user.last_name = msg.from_user.last_name
    user.username = msg.from_user.username
    user.save()
    args = command.args
    await state.clear()
    if args:
        try:
            promo = await sync_to_async(Promo.objects.get)(code=args)
            if promo.active:
                promo.active = False
                promo.save()
                await promo_coder(promo, user, msg, bot)
        except Exception as e:
            if not user.ref_by:
                refer = await sync_to_async(TGUser.objects.filter)(referral_code=args)
                if refer:
                    refer = refer.first()
                    user.ref_by = refer
                    if not user.is_changer:
                        user.is_changer = True
                    user.save()
                    bottoms = await changer_panel_bottom(user)
                    await msg.answer("☀️ *Приветствие*", reply_markup=bottoms, parse_mode="Markdown")
    if user.is_changer:
        bottoms = await changer_panel_bottom(user)
        await msg.answer("☀️ *Приветствие*", reply_markup=bottoms, parse_mode="Markdown")
    shops = await sync_to_async(Shop.objects.filter)(boss=user)
    shop_operator = await sync_to_async(ShopOperator.objects.filter)(operator=user, active=True)
    if shop_operator:
        shop_operator_markup = await shop_operator_panel()
        await msg.answer("🔆 Приветствие!", reply_markup=shop_operator_markup)
    if user.is_admin:
        admin_bottom = await admin_panel()
        await msg.answer("🔆 Приветствие!", reply_markup=admin_bottom)
    if shops:
        shop = shops.first()
        shop_panel_markup = await shop_panel()
        await msg.answer(f"---", parse_mode="Markdown", reply_markup=shop_panel_markup)

