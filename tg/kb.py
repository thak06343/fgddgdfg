from aiogram.types import ReplyKeyboardMarkup, InlineKeyboardButton, KeyboardButton, InlineKeyboardMarkup
from .models import TGUser, Invoice, ReqUsage, Req
from asgiref.sync import sync_to_async


async def changer_panel_bottom(user):
    reqs = await sync_to_async(Req.objects.filter)(active=True, user=user)
    if reqs:
        changer_panel = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[[KeyboardButton(text="📍 Главное"), KeyboardButton(text="P2P: 🟢ON")],
                                                                     [KeyboardButton(text="🔗 Реф система")] ,
                                                                     [KeyboardButton(text="⚙️ Настройки")]])
        return changer_panel
    elif not reqs:
        changer_panel = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
            [KeyboardButton(text="📍 Главное"), KeyboardButton(text="P2P: ⚫️OFF")],
            [KeyboardButton(text="🔗 Реф система")],
            [KeyboardButton(text="⚙️ Настройки")]])
        return changer_panel


async def shop_panel():
    changer_panel = ReplyKeyboardMarkup(resize_keyboard=True,
                                        keyboard=[[KeyboardButton(text="💎 Главное")],
                                                  [KeyboardButton(text="🔗 Статистика")],
                                                  [KeyboardButton(text="⚙️ Настройки")]])
    return changer_panel

async def shop_operator_panel():
    shop_operator_bottoms = ReplyKeyboardMarkup(resize_keyboard=True,
                                                keyboard=[
                                                    [KeyboardButton(text="🔱 Инвойсы")],
                                                    # [KeyboardButton(text="")]
                                                ])
    return shop_operator_bottoms

async def admin_panel():
    admin_bottoms = ReplyKeyboardMarkup(resize_keyboard=True,
                                        keyboard=[
                                            [KeyboardButton(text="🐙 Главное"), KeyboardButton(text="🔱 Инвойсы")],
                                            [KeyboardButton(text="♟ Курсы")],
                                            [KeyboardButton(text="🏵 Промо")]
                                        ])
    return admin_bottoms