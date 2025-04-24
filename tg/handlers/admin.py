from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery, ReactionTypeEmoji
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Filter, Command
from asgiref.sync import sync_to_async
from .utils import get_ltc_usd_rate, admin_balance, transfer_to_admin, PAGE_SIZE, shop_balance, balance_val, \
    changers_current_balance, IsLtcReq
from ..models import TGUser, Invoice, Country, Req, WithdrawalMode, Promo, Shop, ReqUsage
from ..text import admin_invoice_text

router = Router()

class IsAdmin(Filter):
    async def __call__(self, msg: Message):
        try:
            user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
            return user.is_admin
        except Exception as e:
            return False

router.message.filter(IsAdmin())

@router.message(F.text == "🐙 Главное")
async def main_admin(msg: Message):
    user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
    balance, adm_invoices =  await admin_balance(user)
    text = f"💰 *Баланс:* *${round(balance, 2)}*\n"
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⚡️ 𝑳𝑻𝑪", callback_data=f"admin_order_to_withdraw"))
    await msg.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


class WithdrawToAdminState(StatesGroup):
    awaiting_ltc_req = State()

@router.callback_query(F.data == "admin_order_to_withdraw")
async def shop_order_to_withdraw(call: CallbackQuery, state: FSMContext):
    await state.set_state(WithdrawToAdminState.awaiting_ltc_req)
    await call.message.answer("💸 Введите кошелек LTC для вывода:")

@router.message(WithdrawToAdminState.awaiting_ltc_req)
async def awaiting_ltc_to_send_shop(msg: Message, state: FSMContext):
    user = await sync_to_async(TGUser.objects.get)(user_id=msg.from_user.id)
    try:
        ltc_address = msg.text.strip()
        is_ltc_req = await IsLtcReq(ltc_address)
        if is_ltc_req:
            await state.clear()
            balance, adm_invoices =  await admin_balance(user)
            try:
                ltc_usdt_price = await get_ltc_usd_rate()
            except Exception as e:
                await msg.answer(f"❌ Не удалось получить курс LTC. Попробуйте позже.\n{e}")
                return
            ltc_amount = balance / ltc_usdt_price
            amount_in_satoshi = int(ltc_amount * 100_000_000)
            pack = await sync_to_async(WithdrawalMode.objects.create)(user=user, active=True, requisite=ltc_address,
                                                                      ltc_amount=ltc_amount)
            await sync_to_async(pack.invoices.add)(*adm_invoices)
            result = await transfer_to_admin(amount_in_satoshi, ltc_address, pack.id)
            await msg.answer(result)
        else:
            await msg.answer("Неверный LTC адрес, попробуйте еще раз")
    except Exception as e:
        print(e)

@router.message(F.text == "♟ Курсы")
async def manage_courses(msg: Message):
    countries = await sync_to_async(Country.objects.all)()
    builder = InlineKeyboardBuilder()
    text = ""
    for country in countries:
        builder.add(InlineKeyboardButton(text=f"{country.flag} {country.country.upper()}", callback_data=f"change_course_{country.id}"))
        text += f"{country.flag} {country.country.upper()}\n"
        text += f"KZT-{country.country.upper()} = {country.kzt_to_fiat}\n"
        text += f"{country.country.upper()}-USDT = {country.fiat_to_usdt}\n"
        text += f"{country.country.upper()}-USDT = {country.fiat_to_usdt_for_shop} (SHOP PRICE)\n\n"
    builder.adjust(2)
    await msg.answer(text if text else "123", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("change_course_"))
async def change_courses(call: CallbackQuery):
    data = call.data.split("_")
    country = await sync_to_async(Country.objects.get)(id=data[2])
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=f"KZT - {country.country.upper()} ({country.kzt_to_fiat})", callback_data=f"change_kzt_to_fiat_{country.id}"))
    builder.add(InlineKeyboardButton(text=f"{country.country.upper()}-USDT = ({country.fiat_to_usdt})", callback_data=f"change_fiat_to_usdt_{country.id}"))
    builder.add(InlineKeyboardButton(text=f"{country.country.upper()}-USDT = ({country.fiat_to_usdt_for_shop}) SHOP", callback_data=f"change_fiat_to_usdt_for_shop_{country.id}"))
    builder.adjust(1)
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())

class ChangeCountryCoursesState(StatesGroup):
    awaiting_kzt_to_fiat = State()
    awaiting_fiat_to_usdt = State()
    awaiting_fiat_to_usdt_for_shop = State()

@router.callback_query(F.data.startswith("change_kzt_to_fiat_"))
async def change_kzt_to_fiat(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    country = await sync_to_async(Country.objects.get)(id=data[4])
    await state.set_state(ChangeCountryCoursesState.awaiting_kzt_to_fiat)
    await state.update_data(country_id=country.id)
    await call.message.answer(f"Введите значение для KZT - {country.country.upper()}:\n\nТекущее значение = {country.kzt_to_fiat}")

@router.message(ChangeCountryCoursesState.awaiting_kzt_to_fiat)
async def awaiting_kzt_to_fiat(msg: Message, state: FSMContext):
    try:
        new_course = float(msg.text)
        data = await state.get_data()
        country_id = data.get("country_id")
        country = await sync_to_async(Country.objects.get)(id=country_id)
        country.kzt_to_fiat = new_course
        country.save()
        await state.clear()
        await msg.answer(f"Курс KZT - {country.country.upper()} изменен на {new_course}")
    except Exception as e:
        await msg.answer("Введите корректное значение, например 1.5, 2, 3.4")

@router.callback_query(F.data.startswith("change_fiat_to_usdt_"))
async def change_kzt_to_fiat(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    country = await sync_to_async(Country.objects.get)(id=data[4])
    await state.set_state(ChangeCountryCoursesState.awaiting_fiat_to_usdt)
    await state.update_data(country_id=country.id)
    await call.message.answer(f"Введите значение для {country.country.upper()} - USDT:\n\nТекущее значение = {country.awaiting_fiat_to_usdt}")

@router.message(ChangeCountryCoursesState.awaiting_fiat_to_usdt)
async def awaiting_kzt_to_fiat(msg: Message, state: FSMContext):
    try:
        new_course = float(msg.text)
        data = await state.get_data()
        country_id = data.get("country_id")
        country = await sync_to_async(Country.objects.get)(id=country_id)
        country.awaiting_fiat_to_usdt = new_course
        country.save()
        await state.clear()
        await msg.answer(f"Курс {country.country.upper()} - USDT изменен на {new_course}")
    except Exception as e:
        await msg.answer("Введите корректное значение, например 1.5, 2, 3.4")

@router.callback_query(F.data.startswith("change_fiat_to_usdt_for_shop_"))
async def fiat_to_usdt_for_shop(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    country = await sync_to_async(Country.objects.get)(id=data[6])
    await state.set_state(ChangeCountryCoursesState.awaiting_fiat_to_usdt_for_shop)
    await state.update_data(country_id=country.id)
    await call.message.answer(f"Введите значение для {country.country.upper()} - USDT(SHOP):\n\nТекущее значение = {country.fiat_to_usdt_for_shop}")

@router.message(ChangeCountryCoursesState.awaiting_fiat_to_usdt)
async def awaiting_kzt_to_fiat(msg: Message, state: FSMContext):
    try:
        new_course = float(msg.text)
        data = await state.get_data()
        country_id = data.get("country_id")
        country = await sync_to_async(Country.objects.get)(id=country_id)
        country.fiat_to_usdt_for_shop = new_course
        country.save()
        await state.clear()
        await msg.answer(f"Курс {country.country.upper()} - USDT(SHOP) изменен на {new_course}")
    except Exception as e:
        await msg.answer("Введите корректное значение, например 1.5, 2, 3.4")

@router.message(F.text == "🏵 Промо")
async def admin_promo_create(msg: Message):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🏪 Магазины", callback_data="admin_all_shops"))
    builder.add(InlineKeyboardButton(text="➕ Новый магазин", callback_data="admin_new_shop_promo"))
    builder.add(InlineKeyboardButton(text="➕ Новый оператор обмена", callback_data="admin_new_operator_promo"))
    builder.adjust(1)
    text = "Выберите где хотите создать промокод:"
    await msg.answer(text, reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin_all_shops")
async def admin_all_shops(call: CallbackQuery):
    all_shops = await sync_to_async(Shop.objects.all)()
    if all_shops:
        total_pages = (len(all_shops) + PAGE_SIZE - 1) // PAGE_SIZE
        page_number = 1

        @router.callback_query(F.data.startswith("next_page_"))
        async def handle_next_page(call: CallbackQuery):
            page_number = int(call.data.split("_")[2]) + 1
            if page_number > total_pages:
                page_number = total_pages
            await send_invoices_page(call, page_number, total_pages)

        @router.callback_query(F.data.startswith("prev_page_"))
        async def handle_next_page(call: CallbackQuery):
            page_number = int(call.data.split("_")[2]) - 1
            if page_number < total_pages:
                page_number = total_pages
            await send_invoices_page(call, page_number, total_pages)

        async def send_invoices_page(call, page_number, total_pages):
            start_index = (page_number - 1) * PAGE_SIZE
            end_index = min(start_index + PAGE_SIZE, len(all_shops))
            inv_page = all_shops[start_index:end_index]

            builder = InlineKeyboardBuilder()
            for shop in inv_page:
                builder.add(InlineKeyboardButton(text=f"{shop.name.upper()}", callback_data=f"admin_promo_show_shop_{shop.id}"))
            builder.adjust(2)
            if page_number > 1:
                builder.row(
                    InlineKeyboardButton(text=f"< Предыдущая страница", callback_data=f"prev_page_{page_number - 1}"))
            if page_number < total_pages:
                builder.row(
                    InlineKeyboardButton(text=f"> Следующая страница", callback_data=f"next_page_{page_number + 1}"))
            await call.message.edit_reply_markup(reply_markup=builder.as_markup())

        await send_invoices_page(call, page_number, total_pages)
    else:
        await call.answer("Пусто!")

@router.callback_query(F.data.startswith("admin_promo_show_shop_"))
async def admin_show_shop(call: CallbackQuery):
    data = call.data.split("_")
    shop = await sync_to_async(Shop.objects.get)(id=data[4])
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=f"Создать оператора для {shop.name.upper()}", callback_data=f"admin_shop_operator_promo_{shop.id}"))
    builder.row(InlineKeyboardButton(text="< Назад", callback_data="admin_all_shops"))
    builder.adjust(1)
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("admin_shop_operator_promo_"))
async def admin_shop_operator_promo(call: CallbackQuery, bot: Bot):
    data = call.data.split("_")
    shop = await sync_to_async(Shop.objects.get)(id=data[4])
    new_operator_promo = await sync_to_async(Promo.objects.create)(type="new_shop_operator", shop=shop)
    bot_info = await bot.get_me()
    bot_user = bot_info.username
    link = f"https://t.me/{bot_user}?start={new_operator_promo.code}"
    await call.message.answer(f"💡 `{shop.name.upper()}`\n\n`{link}`", parse_mode="Markdown")

@router.callback_query(F.data == "admin_new_shop_promo")
async def admin_new_shop_promo(call: CallbackQuery, bot: Bot):
    new_promo = await sync_to_async(Promo.objects.create)(type="new_shop")
    bot_info = await bot.get_me()
    bot_username = bot_info.username
    link = f"https://t.me/{bot_username}?start={new_promo.code}"
    await call.message.answer(f"`{link}`\n\nОтправьте ссылку новому магазину!", parse_mode="Markdown")

@router.callback_query(F.data == "admin_new_operator_promo")
async def admin_new_shop_promo(call: CallbackQuery, bot: Bot):
    new_promo = await sync_to_async(Promo.objects.create)(type="new_changer")
    bot_info = await bot.get_me()
    bot_username = bot_info.username
    text = f"https://t.me/{bot_username}?start={new_promo.code}"
    await call.message.answer(f"`{text}`\n\nОтправьте ссылку новому оператору!", parse_mode="Markdown")

@router.message(F.text == "🔱 Инвойсы")
async def admin_all_invoices(msg: Message):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Все", callback_data="admin_all_invoices"))
    builder.add(InlineKeyboardButton(text="Операторы", callback_data="admin_all_changers"))
    builder.add(InlineKeyboardButton(text="Магазины", callback_data="admin_all_shops_invoices"))
    builder.add(InlineKeyboardButton(text="Принятые", callback_data="admin_all_accepted_invoices"))
    builder.add(InlineKeyboardButton(text="Просроченные", callback_data="admin_all_expired_invoices"))
    builder.add(InlineKeyboardButton(text="Отправлена фото", callback_data="admin_all_photo_sent_invoices"))
    builder.add(InlineKeyboardButton(text="Активные", callback_data="admin_active_usages"))
    builder.adjust(2)
    await msg.answer("123", reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin_active_usages")
async def admin_active_usages(call: CallbackQuery):
    usages = await sync_to_async(ReqUsage.objects.filter)(active=True)
    usages = usages.order_by('-date_used')
    if usages:
        total_pages = (len(usages) + PAGE_SIZE - 1) // PAGE_SIZE
        page_number = 1

        @router.callback_query(F.data.startswith("next_page_"))
        async def handle_next_page(call: CallbackQuery):
            page_number = int(call.data.split("_")[2])
            if page_number > total_pages:
                page_number = total_pages
            await send_invoices_page(call, page_number, total_pages)

        @router.callback_query(F.data.startswith("prev_page_"))
        async def handle_next_page(call: CallbackQuery):
            page_number = int(call.data.split("_")[2])
            if page_number < total_pages:
                page_number = total_pages
            await send_invoices_page(call, page_number, total_pages)

        async def send_invoices_page(call, page_number, total_pages):
            start_index = (page_number - 1) * PAGE_SIZE
            end_index = min(start_index + PAGE_SIZE, len(usages))
            usage_page = usages[start_index:end_index]

            builder = InlineKeyboardBuilder()
            for usage in usage_page:
                active_not = ''
                if usage.usage_inv.accepted:
                    active_not += "✅"
                if usage.active:
                    active_not += "♻️"
                if usage.photo:
                    active_not += "🖼"
                builder.add(InlineKeyboardButton(
                        text=f"{active_not}{usage.date_used.strftime('%d.%m')}|+{usage.usage_inv.amount_in_kzt}KZT",
                        callback_data=f"admin_invoice_{usage.usage_inv.id}"))
            builder.adjust(2)
            if page_number > 1:
                builder.row(
                    InlineKeyboardButton(text=f"< Предыдущая страница", callback_data=f"prev_page_{page_number - 1}"))
            if page_number < total_pages:
                builder.row(
                    InlineKeyboardButton(text=f"> Следующая страница", callback_data=f"next_page_{page_number + 1}"))
            builder.row(InlineKeyboardButton(text="< Назад", callback_data=f"back_to_invoices"))
            await call.message.edit_reply_markup(reply_markup=builder.as_markup())

        await send_invoices_page(call, page_number, total_pages)
    else:
        await call.message.answer("Нет инвойсов!")

@router.callback_query(F.data == "admin_all_shops_invoices")
async def admin_all_shops(call: CallbackQuery):
    shops = await sync_to_async(Shop.objects.all)()
    builder = InlineKeyboardBuilder()
    for shop in shops:
        builder.add(InlineKeyboardButton(text=f"{shop.name}", callback_data=f"admin_show_shop_invoices_{shop.id}"))
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="< Назад", callback_data="back_to_invoices"))
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("admin_show_shop_invoices_"))
async def admin_show_shop_invoices(call: CallbackQuery):
    data = call.data.split("_")
    shop = await sync_to_async(Shop.objects.get)(id=data[4])
    invoices = await sync_to_async(Invoice.objects.filter)(shop=shop)
    invoices = invoices.order_by('-date_used')
    if invoices:
        total_pages = (len(invoices) + PAGE_SIZE - 1) // PAGE_SIZE
        page_number = 1

        @router.callback_query(F.data.startswith("next_page_"))
        async def handle_next_page(call: CallbackQuery):
            page_number = int(call.data.split("_")[2])
            if page_number > total_pages:
                page_number = total_pages
            await send_invoices_page(call, page_number, total_pages)

        @router.callback_query(F.data.startswith("prev_page_"))
        async def handle_next_page(call: CallbackQuery):
            page_number = int(call.data.split("_")[2])
            if page_number < total_pages:
                page_number = total_pages
            await send_invoices_page(call, page_number, total_pages)

        async def send_invoices_page(call, page_number, total_pages):
            start_index = (page_number - 1) * PAGE_SIZE
            end_index = min(start_index + PAGE_SIZE, len(invoices))
            inv_page = invoices[start_index:end_index]

            builder = InlineKeyboardBuilder()
            for invoice in inv_page:
                req_usage = await sync_to_async(ReqUsage.objects.filter)(usage_inv=invoice)
                if req_usage:
                    req_usage = req_usage.first()
                    active_not = ''
                    if invoice.accepted:
                        active_not += "✅"
                    elif req_usage.active:
                        active_not += "♻️"
                    else:
                        active_not += "❌"
                    builder.add(InlineKeyboardButton(
                            text=f"{active_not}{invoice.date_used.strftime('%d.%m')}|+{invoice.amount_in_kzt}KZT",
                            callback_data=f"admin_invoice_{invoice.id}"))
            builder.adjust(2)
            if page_number > 1:
                builder.row(
                    InlineKeyboardButton(text=f"< Предыдущая страница", callback_data=f"prev_page_{page_number - 1}"))
            if page_number < total_pages:
                builder.row(
                    InlineKeyboardButton(text=f"> Следующая страница", callback_data=f"next_page_{page_number + 1}"))
            builder.row(InlineKeyboardButton(text="< Назад", callback_data=f"admin_all_shops"))
            await call.message.edit_reply_markup(reply_markup=builder.as_markup())

        await send_invoices_page(call, page_number, total_pages)
    else:
        await call.message.answer("Нет инвойсов!")

@router.callback_query(F.data == "admin_all_changers")
async def admin_all_changers(call: CallbackQuery):
    changers = await sync_to_async(TGUser.objects.filter)(is_changer=True)
    builder = InlineKeyboardBuilder()
    for changer in changers:
        builder.add(InlineKeyboardButton(text=f"{changer.username if changer.username else changer.first_name}", callback_data=f"admin_show_changer_{changer.id}"))
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="< Назад", callback_data="back_to_invoices"))
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("admin_show_changer_"))
async def admin_show_changer(call: CallbackQuery):
    data = call.data.split("_")
    changer = await sync_to_async(TGUser.objects.get)(id=data[3])
    reqs = await sync_to_async(Req.objects.filter)(user=changer)
    builder = InlineKeyboardBuilder()
    if reqs:
        for req in reqs:
            short_name = req.name[:3].upper()
            last_digits = req.cart[-4:] if req.cart and len(req.cart) >= 4 else "****"
            builder.add(InlineKeyboardButton(text=f"{short_name}|{last_digits}", callback_data=f"admin_req_invoices_{req.id}"))
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="< Назад", callback_data="admin_all_changers"))
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("admin_req_invoices_"))
async def admin_req_invoices(call: CallbackQuery):
    data = call.data.split("_")
    req = await sync_to_async(Req.objects.get)(id=data[3])
    invoices = await sync_to_async(Invoice.objects.filter)(req=req)
    invoices = invoices.order_by('-date_used')
    if invoices:
        total_pages = (len(invoices) + PAGE_SIZE - 1) // PAGE_SIZE
        page_number = 1

        @router.callback_query(F.data.startswith("next_page_"))
        async def handle_next_page(call: CallbackQuery):
            page_number = int(call.data.split("_")[2])
            if page_number > total_pages:
                page_number = total_pages
            await send_invoices_page(call, page_number, total_pages)

        @router.callback_query(F.data.startswith("prev_page_"))
        async def handle_next_page(call: CallbackQuery):
            page_number = int(call.data.split("_")[2])
            if page_number < total_pages:
                page_number = total_pages
            await send_invoices_page(call, page_number, total_pages)

        async def send_invoices_page(call, page_number, total_pages):
            start_index = (page_number - 1) * PAGE_SIZE
            end_index = min(start_index + PAGE_SIZE, len(invoices))
            inv_page = invoices[start_index:end_index]

            builder = InlineKeyboardBuilder()
            for invoice in inv_page:
                req_usage = await sync_to_async(ReqUsage.objects.filter)(usage_inv=invoice)
                if req_usage:
                    req_usage = req_usage.first()
                    if req_usage.photo:
                        active_not = ''
                        if invoice.accepted:
                            active_not += "✅"
                        elif req_usage.active:
                            active_not += "♻️"
                        else:
                            active_not += "❌"
                        builder.add(InlineKeyboardButton(
                            text=f"{active_not}{invoice.date_used.strftime('%d.%m')}|+{invoice.amount_in_kzt}KZT",
                            callback_data=f"admin_invoice_{invoice.id}"))
            builder.adjust(2)
            if page_number > 1:
                builder.row(
                    InlineKeyboardButton(text=f"< Предыдущая страница", callback_data=f"prev_page_{page_number - 1}"))
            if page_number < total_pages:
                builder.row(
                    InlineKeyboardButton(text=f"> Следующая страница", callback_data=f"next_page_{page_number + 1}"))
            builder.row(InlineKeyboardButton(text="< Назад", callback_data=f"admin_show_changer_{req.user.id}"))
            await call.message.edit_reply_markup(reply_markup=builder.as_markup())

        await send_invoices_page(call, page_number, total_pages)
    else:
        await call.message.answer("Нет инвойсов!")

@router.callback_query(F.data == "back_to_invoices")
async def back_to_invoices(call: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Все", callback_data="admin_all_invoices"))
    builder.add(InlineKeyboardButton(text="Операторы", callback_data="admin_all_changers"))
    builder.add(InlineKeyboardButton(text="Магазины", callback_data="admin_all_shops_invoices"))
    builder.add(InlineKeyboardButton(text="Принятые", callback_data="admin_all_accepted_invoices"))
    builder.add(InlineKeyboardButton(text="Просроченные", callback_data="admin_all_expired_invoices"))
    builder.add(InlineKeyboardButton(text="Отправлена фото", callback_data="admin_all_photo_sent_invoices"))
    builder.add(InlineKeyboardButton(text="Активные", callback_data="admin_active_usages"))
    builder.adjust(2)
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin_all_photo_sent_invoices")
async def admin_all_photo_sent_invoices(call: CallbackQuery):
    invoices = await sync_to_async(lambda: Invoice.objects.filter(
        id__in=ReqUsage.objects.filter(photo__isnull=False).values_list('usage_inv_id', flat=True)
    ))()
    invoices = invoices.order_by('-date_used')
    if invoices:
        total_pages = (len(invoices) + PAGE_SIZE - 1) // PAGE_SIZE
        page_number = 1

        @router.callback_query(F.data.startswith("next_page_"))
        async def handle_next_page(call: CallbackQuery):
            page_number = int(call.data.split("_")[2])
            if page_number > total_pages:
                page_number = total_pages
            await send_invoices_page(call, page_number, total_pages)

        @router.callback_query(F.data.startswith("prev_page_"))
        async def handle_next_page(call: CallbackQuery):
            page_number = int(call.data.split("_")[2])
            if page_number < total_pages:
                page_number = total_pages
            await send_invoices_page(call, page_number, total_pages)

        async def send_invoices_page(call, page_number, total_pages):
            start_index = (page_number - 1) * PAGE_SIZE
            end_index = min(start_index + PAGE_SIZE, len(invoices))
            inv_page = invoices[start_index:end_index]

            builder = InlineKeyboardBuilder()
            for invoice in inv_page:
                req_usage = await sync_to_async(ReqUsage.objects.filter)(usage_inv=invoice)
                if req_usage:
                    req_usage = req_usage.first()
                    if req_usage.photo:
                        active_not = ''
                        if invoice.accepted:
                            active_not += "✅"
                        elif req_usage.active:
                            active_not += "♻️"
                        else:
                            active_not += "❌"
                        builder.add(InlineKeyboardButton(
                            text=f"{active_not}{invoice.date_used.strftime('%d.%m')}|+{invoice.amount_in_kzt}KZT",
                            callback_data=f"admin_invoice_{invoice.id}"))
            builder.adjust(2)
            if page_number > 1:
                builder.row(
                    InlineKeyboardButton(text=f"< Предыдущая страница", callback_data=f"prev_page_{page_number - 1}"))
            if page_number < total_pages:
                builder.row(
                    InlineKeyboardButton(text=f"> Следующая страница", callback_data=f"next_page_{page_number + 1}"))
            await call.message.edit_reply_markup(reply_markup=builder.as_markup())

        await send_invoices_page(call, page_number, total_pages)
    else:
        await call.message.answer("Нет инвойсов!")

@router.callback_query(F.data == "admin_all_expired_invoices")
async def admin_all_expired_invoices(call: CallbackQuery):
    invoices = await sync_to_async(Invoice.objects.filter)(status="timeout")
    invoices = invoices.order_by('-date_used')
    if invoices:
        total_pages = (len(invoices) + PAGE_SIZE - 1) // PAGE_SIZE
        page_number = 1

        @router.callback_query(F.data.startswith("next_page_"))
        async def handle_next_page(call: CallbackQuery):
            page_number = int(call.data.split("_")[2])
            if page_number > total_pages:
                page_number = total_pages
            await send_invoices_page(call, page_number, total_pages)

        @router.callback_query(F.data.startswith("prev_page_"))
        async def handle_next_page(call: CallbackQuery):
            page_number = int(call.data.split("_")[2])
            if page_number < total_pages:
                page_number = total_pages
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
                    active_not += "❌"
                builder.add(InlineKeyboardButton(
                    text=f"{active_not}{invoice.date_used.strftime('%d.%m')}|+{invoice.amount_in_kzt}KZT",
                    callback_data=f"admin_invoice_{invoice.id}"))
            builder.adjust(2)
            if page_number > 1:
                builder.row(
                    InlineKeyboardButton(text=f"< Предыдущая страница", callback_data=f"prev_page_{page_number - 1}"))
            if page_number < total_pages:
                builder.row(
                    InlineKeyboardButton(text=f"> Следующая страница", callback_data=f"next_page_{page_number + 1}"))
            await call.message.edit_reply_markup(reply_markup=builder.as_markup())

        await send_invoices_page(call, page_number, total_pages)
    else:
        await call.message.answer("Нет инвойсов!")

@router.callback_query(F.data == "admin_all_accepted_invoices")
async def admin_all_accepted_invoices(call: CallbackQuery):
    invoices = await sync_to_async(Invoice.objects.filter)(accepted=True)
    invoices = invoices.order_by('-date_used')
    if invoices:
        total_pages = (len(invoices) + PAGE_SIZE - 1) // PAGE_SIZE
        page_number = 1

        @router.callback_query(F.data.startswith("next_page_"))
        async def handle_next_page(call: CallbackQuery):
            page_number = int(call.data.split("_")[2])
            if page_number > total_pages:
                page_number = total_pages
            await send_invoices_page(call, page_number, total_pages)

        @router.callback_query(F.data.startswith("prev_page_"))
        async def handle_next_page(call: CallbackQuery):
            page_number = int(call.data.split("_")[2])
            if page_number < total_pages:
                page_number = total_pages
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
                    active_not += "❌"
                builder.add(InlineKeyboardButton(
                    text=f"{active_not}{invoice.date_used.strftime('%d.%m')}|+{invoice.amount_in_kzt}KZT",
                    callback_data=f"admin_invoice_{invoice.id}"))
            builder.adjust(2)
            if page_number > 1:
                builder.row(
                    InlineKeyboardButton(text=f"< Предыдущая страница", callback_data=f"prev_page_{page_number - 1}"))
            if page_number < total_pages:
                builder.row(
                    InlineKeyboardButton(text=f"> Следующая страница", callback_data=f"next_page_{page_number + 1}"))
            await call.message.edit_reply_markup(reply_markup=builder.as_markup())

        await send_invoices_page(call, page_number, total_pages)
    else:
        await call.message.answer("Нет инвойсов!")

@router.callback_query(F.data == "admin_all_invoices")
async def admin_all_invoices(call: CallbackQuery):
    invoices = await sync_to_async(Invoice.objects.all)()
    invoices = invoices.order_by('-date_used')
    if invoices:
        total_pages = (len(invoices) + PAGE_SIZE - 1) // PAGE_SIZE
        page_number = 1

        @router.callback_query(F.data.startswith("next_page_"))
        async def handle_next_page(call: CallbackQuery):
            page_number = int(call.data.split("_")[2])
            # if page_number > total_pages:
            #     page_number = total_pages
            await send_invoices_page(call, page_number, total_pages)

        @router.callback_query(F.data.startswith("prev_page_"))
        async def handle_next_page(call: CallbackQuery):
            page_number = int(call.data.split("_")[2])
            # if page_number < total_pages:
            #     page_number = total_pages
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
                    active_not += "❌"
                builder.add(InlineKeyboardButton(
                    text=f"{active_not}{invoice.date_used.strftime('%d.%m')}|+{invoice.amount_in_kzt}KZT",
                    callback_data=f"admin_invoice_{invoice.id}"))
            builder.adjust(2)
            if page_number > 1:
                builder.row(
                    InlineKeyboardButton(text=f"< Предыдущая страница", callback_data=f"prev_page_{page_number - 1}"))
            if page_number < total_pages:
                builder.row(
                    InlineKeyboardButton(text=f"> Следующая страница", callback_data=f"next_page_{page_number + 1}"))
            await call.message.edit_reply_markup(reply_markup=builder.as_markup())

        await send_invoices_page(call, page_number, total_pages)
    else:
        await call.message.answer("Нет инвойсов!")

@router.callback_query(F.data.startswith("admin_invoice_"))
async def admin_invoice(call: CallbackQuery):
    data = call.data.split("_")
    invoice = await sync_to_async(Invoice.objects.get)(id=data[2])
    text = admin_invoice_text.format(operator=invoice.req.user.username if invoice.req.user.username else invoice.req.user.first_name,
                                     shop=invoice.shop.name.upper(), amount=round(invoice.amount_in_kzt, 2), date=invoice.date_used.strftime('%d.%m.%Y %H:%M'),
                                     amount_kgs=round(invoice.amount_in_fiat, 2), amount_usdt=round(invoice.amount_in_usdt_for_changer, 2))
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=f"Принять от имени {invoice.req.user.username if invoice.req.user.username else invoice.req.user.first_name}",
                                     callback_data=f"admin_accept_invoice_{invoice.id}"))

    if invoice.status != "deleted" and not invoice.accepted:
        builder.row(InlineKeyboardButton(text="Удалить", callback_data=f"admin_del_invoice_{invoice.id}"))
    if invoice.status == "deleted" and not invoice.accepted:
        text += "\n❌ Инвойс удален"
    if invoice.accepted:
        text += "\n\nИНВОЙС ПОДТВЕРЖДЕН!"

    req_usages = await sync_to_async(lambda: ReqUsage.objects.filter(usage_inv=invoice, photo__isnull=False))()
    for req_usage in req_usages:
        if req_usage.photo:
            builder.add(InlineKeyboardButton(text="Фото Чека", callback_data=f"admin_show_photo_{req_usage.id}"))

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text=f"✍️ Изменить сумму {invoice.req.country.country}", callback_data=f"admin_change_invoice_fiat_{invoice.id}"))
    builder.row(InlineKeyboardButton(text=f"< Назад", callback_data="back_to_invoices"))
    await call.message.edit_text(text=text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.callback_query(F.data.startswith("admin_change_invoice_fiat_"))
async def admin_change_invoice_fiat(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    invoice = await sync_to_async(Invoice.objects.get)(id=data[4])
    await call.answer("Введите сумму", show_alert=True)
    await state.set_state(ChangeFiatAdminState.awaiting_amount)
    await state.update_data(invoice_id=invoice.id)

class ChangeFiatAdminState(StatesGroup):
    awaiting_amount = State()

@router.message(ChangeFiatAdminState.awaiting_amount)
async def awaiting_amount_invoice(msg: Message, state: FSMContext, bot: Bot):
    try:
        amount = int(msg.text)
        data = await state.get_data()
        invoice_id = data.get("invoice_id")
        invoice = await sync_to_async(Invoice.objects.get)(id=invoice_id)
        if amount <= invoice.amount_in_fiat:
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
                fiat = amount / country.kzt_to_fiat
                usdt_for_changer = fiat / country.fiat_to_usdt
                usdt_for_shop = fiat / country.fiat_to_usdt_for_shop
            else:
                fiat = amount * country.kzt_to_fiat
                usdt_for_changer = fiat / country.fiat_to_usdt
                usdt_for_shop = fiat / country.fiat_to_usdt_for_shop
            invoice.amount_in_usdt = usdt_for_shop
            invoice.amount_in_usdt_for_changer = usdt_for_changer
            invoice.save()
        await state.clear()
    except Exception as e:
        print(e)

@router.message(Command("bc"))
async def admin_show_balance(msg: Message):
    changers = await sync_to_async(TGUser.objects.filter)(is_changer=True)
    text = " "
    for changer in changers:
        balance, ref_balance = await changers_current_balance(changer)
        total_amount_val, awaiting_usdt = await balance_val(changer)
        text += (f"{changer.username if changer.username else changer.first_name}\n"
                 f"${round(total_amount_val, 2)} на карте\n"
                 f"{round(awaiting_usdt, 2)} ожидающие платежи\n"
                 f"${round(balance, 2)}Не выведенный баланс\n\n")
    await msg.answer(text)

@router.message(Command("balance"))
async def balance(msg: Message):
    shops = await sync_to_async(Shop.objects.all)()
    text = " "
    for shop in shops:
        balance, invs = await shop_balance(shop)
        text += (f"{shop.name}\n"
                 f"${round(balance, 2)} {len(invs)}шт\n\n")
    await msg.answer(text)

@router.callback_query(F.data.startswith("admin_accept_invoice_"))
async def admin_accept_invoice(call: CallbackQuery):
    data = call.data.split("_")
    invoice = await sync_to_async(Invoice.objects.get)(id=data[3])
    invoice.accepted = True
    invoice.save()
    await call.answer("Инвойс принят!", show_alert=True)
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Обновить", callback_data=f"admin_invoice_{invoice.id}"))
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("admin_show_photo_"))
async def admin_show_photo(call: CallbackQuery):
    data = call.data.split("_")
    req_usage = await sync_to_async(ReqUsage.objects.get)(id=data[3])
    try:
        await call.message.answer_photo(req_usage.photo)
    except Exception as e:
        await call.message.answer_document(req_usage.photo)

@router.callback_query(F.data.startswith("admin_del_invoice_"))
async def admin_del_invoice(call: CallbackQuery):
    data = call.data.split("_")
    invoice = await sync_to_async(Invoice.objects.get)(id=data[3])
    invoice.status = "deleted"
    invoice.save()
    await call.answer("Инвойс удалён!", show_alert=True)

@router.callback_query(F.data.startswith("admindecline_invoice_"))
async def decline_invoice_admin(call: CallbackQuery):
    data = call.data.split("_")
    invoice = await sync_to_async(Invoice.objects.get)(id=data[2])
    invoice.status = "deleted"
    invoice.save()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"Удалить", callback_data=f"admindelete_invoice_{invoice.id}"))
    builder.add(InlineKeyboardButton(text=f"Ввести 4 цифры", callback_data=f"admintype_4digits_{invoice.id}_{data[3]}"))
    builder.add(InlineKeyboardButton(text="Перевести", callback_data=f"adminchange_operator_{invoice.id}_{data[3]}"))
    builder.row(InlineKeyboardButton(text="< Назад", callback_data=f"admin_back_to_accept_{invoice.id}_{data[3]}"))
    builder.adjust(1, 2, 1)
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("adminchange_operator_"))
async def admin_change_operator(call: CallbackQuery):
    data = call.data.split("_")
    changers = await sync_to_async(TGUser.objects.filter)(is_changer=True)
    builder = InlineKeyboardBuilder()
    for changer in changers:
        builder.add(InlineKeyboardButton(text=f"{changer.username if changer.username else changer.first_name}", callback_data=f"adminsend_invoice_{data[2]}_{data[3]}_{changer.user_id}"))
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="< Назад", callback_data=f"admindecline_invoice_{data[2]}_{data[3]}"))
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("adminsend_invoice_"))
async def admin_send_invoice(call: CallbackQuery, bot: Bot):
    data = call.data.split("_")
    usage = await sync_to_async(ReqUsage.objects.get)(id=data[3])
    invoice = await sync_to_async(Invoice.objects.get)(id=data[2])
    req = invoice.req
    short_name = req.name[:3].upper()
    last_digits = req.cart[-4:] if req.cart and len(req.cart) >= 4 else "****"
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=f"✅ ({invoice.amount_in_kzt}T) {short_name} *{last_digits}",
                                     callback_data=f"accept_invoice_{invoice.id}"))
    builder.add(InlineKeyboardButton(text=f"✍️ Др сумма", callback_data=f"accept_and_change_fiat_{invoice.id}"))
    builder.add(InlineKeyboardButton(text="❌", callback_data=f"decline_invoice_{invoice.id}"))
    builder.adjust(1)
    try:
        await bot.send_photo(chat_id=str(data[4]), photo=usage.photo,
                             reply_markup=builder.as_markup())
    except Exception as e:
        await bot.send_document(chat_id=str(data[4]), document=usage.photo,
                                reply_markup=builder.as_markup())
    await call.answer("Отправлено!", show_alert=True)

@router.callback_query(F.data.startswith("admindelete_invoice_"))
async def decline_invoice_admin(call: CallbackQuery):
    data = call.data.split("_")
    invoice = await sync_to_async(Invoice.objects.get)(id=data[2])
    invoice.status = "deleted"
    invoice.save()
    await call.answer("Инвойс удалён!", show_alert=True)

class Admin4Digits(StatesGroup):
    awaiting_digits = State()

@router.callback_query(F.data.startswith("admintype_4digits_"))
async def admin_type_4digits(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    await state.set_state(Admin4Digits.awaiting_digits)
    await state.update_data(invoice_id=data[2], usage_id=data[3])
    await call.answer("Введите 4 последние цифры на карте")

@router.message(Admin4Digits.awaiting_digits)
async def awaiting_digits(msg: Message, state: FSMContext, bot: Bot):
    if msg.text:
        text = msg.text.strip()
        if len(text) == 4:
            try:
                req = await sync_to_async(Req.objects.filter)(cart__endswith=text)
                if req:
                    req = req.first()
                    data = await state.get_data()
                    invoice_id = int(data.get("invoice_id"))
                    usage_id = int(data.get("usage_id"))

                    usage = await sync_to_async(ReqUsage.objects.get)(id=usage_id)
                    invoice = await sync_to_async(Invoice.objects.get)(id=invoice_id)
                    short_name = req.name[:3].upper()
                    last_digits = req.cart[-4:] if req.cart and len(req.cart) >= 4 else "****"
                    builder = InlineKeyboardBuilder()
                    builder.add(InlineKeyboardButton(text=f"✅ ({invoice.amount_in_kzt}T) {short_name} *{last_digits}", callback_data=f"accept_invoice_{invoice_id}"))
                    builder.add(InlineKeyboardButton(text=f"✍️ Др сумма", callback_data=f"accept_and_change_fiat_{invoice_id}"))
                    builder.add(InlineKeyboardButton(text="❌", callback_data=f"decline_invoice_{invoice_id}"))
                    builder.adjust(1)
                    try:
                        await bot.send_photo(chat_id=req.user.user_id, photo=usage.photo,
                                             reply_markup=builder.as_markup())
                    except Exception as e:
                        await bot.send_document(chat_id=req.user.user_id, document=usage.photo,
                                             reply_markup=builder.as_markup())
                    await state.clear()
                else:
                    await msg.answer("Владелец не найден")
                    await state.clear()
            except Exception as e:
                await msg.answer(e)
        else:
            await msg.answer("Ошибка, попробуйте заново")
            await state.clear()


@router.callback_query(F.data == "admin_back_to_accept")
async def admin_back_to_accept(call: CallbackQuery):
    data = call.data.split("_")
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="✅", callback_data=f"admin_accept_invoice_{data[4]}_{data[5]}"))
    builder.add(
        InlineKeyboardButton(text="❌", callback_data=f"admindecline_invoice_{data[4]}_{data[5]}"))
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())

