from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery, ReactionTypeEmoji
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Filter, Command, CommandObject
from asgiref.sync import sync_to_async
from .utils import get_ltc_usd_rate, admin_balance, transfer_to_admin, PAGE_SIZE, shop_balance, balance_val, \
    changers_current_balance, IsLtcReq
from ..models import TGUser, Invoice, Country, Req, WithdrawalMode, Promo, Shop, ReqUsage, OneTimeReq
from ..text import admin_invoice_text

router = Router()

class IsAdmin(Filter):
    async def __call__(self, msg: Message):
        try:
            user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
            return user.is_super_admin
        except Exception as e:
            return False

router.message.filter(IsAdmin())

@router.message(Command("onereq"))
async def one_time_req(msg: Message, args: CommandObject):
    user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
    if args:
        parts = args.text.strip().split()
        if len(parts) != 3:
            await msg.answer("Неверный формат. Используй: /onereq <4 цифры карты> <gte> <lte>")
            return

        cart_digits, gte_str, lte_str = parts
        if not (cart_digits.isdigit() and len(cart_digits) == 4 and gte_str.isdigit() and lte_str.isdigit()):
            await msg.answer("Ошибка в данных. Все аргументы должны быть числами.")
            return

        try:
            req = await sync_to_async(lambda: Req.objects.filter(cart__endswith=cart_digits, user=user).first())()

            if not req:
                await msg.answer("Запрос с такими 4 цифрами не найден.")
                return

            one_time_req = await sync_to_async(OneTimeReq.objects.create)(one_req=req,gte=int(gte_str),lte=int(lte_str),active=True)

            await msg.answer(f"OneTimeReq успешно создан:\nReq: {req.name}\nGTE: {gte_str}\nLTE: {lte_str}")

        except Exception as e:
            await msg.answer(f"Ошибка: {str(e)}")
    else:
        await msg.answer("Пожалуйста, укажи аргументы. Пример: /onereq 1234 5000 9000")



