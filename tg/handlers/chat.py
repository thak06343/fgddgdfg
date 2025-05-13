from collections import defaultdict

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery, ReactionTypeEmoji
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Filter, Command
from asgiref.sync import sync_to_async
from .utils import get_ltc_usd_rate, transfer_to_admin, PAGE_SIZE, shop_balance, balance_val, \
    changers_current_balance, IsLtcReq, sheff_balance
from ..models import TGUser, Invoice, Country, Req, WithdrawalMode, Promo, Shop, ReqUsage
from ..text import admin_invoice_text

router = Router()


@router.message(Command("reg"))
async def chat_req(msg: Message):
    user, created = await sync_to_async(TGUser.objects.get_or_create)(user_id=msg.from_user.id)
    if user.is_admin:
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="Добавить новый", callback_data="admin_chat_new"))
        builder.add(InlineKeyboardButton(text="Добавить в существующий", callback_data="admin_chat_old"))
        builder.adjust(1)
        await msg.answer("Выберите действие:", reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin_chat_new")
async def admin_chat_new(call: CallbackQuery):
    shop, created = await sync_to_async(Shop.objects.get_or_create)(chat_id=call.message.chat.id, name=call.message.chat.username)
    await call.answer(F"Магазин создан, название: {shop.id} {shop.name}")

class Choose(StatesGroup):
    awaiting_name = State()

@router.callback_query(F.data == "admin_chat_old")
async def admin_chat_old(call: CallbackQuery, state: FSMContext):
    await call.answer("Укажите id:")
    await state.set_state(Choose.awaiting_name)

@router.message(Choose.awaiting_name)
async def awaiting_name(msg: Message, state: FSMContext):
    try:
        shop = await sync_to_async(Shop.objects.get)(id=msg.text)
        shop.chat_id = msg.chat.id
        shop.save()
        await msg.answer("Успешно 👍")
    except Exception as e:
        print(e)

class InChatFilter(Filter):
    async def __call__(self, msg: Message):
        try:
            shop = await sync_to_async(Shop.objects.filter)(chat_id=msg.chat.id)
            if shop:
                return True
            else:
                return False
        except Exception as e:
            return False

router.message.filter(InChatFilter())

@router.message(Command("b"))
async def chat_balance(msg: Message):
    shop = await sync_to_async(Shop.objects.get)(chat_id=msg.chat.id)
    balance, invoices = await shop_balance(shop)
    text = f"💰 *Баланс:* *${round(balance, 2)}*\n"
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=f"⚡️ 𝑳𝑻𝑪 ({shop.prc}%)", callback_data=f"shop_order_to_withdraw"))
    await msg.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

# @router.message(Command("r"))
# async def get_chat_reqs(msg: Message):
#