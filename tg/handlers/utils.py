import asyncio
import re

from aiogram.types import InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
import os
from dotenv import load_dotenv
load_dotenv()
import aiohttp
from aiogram.utils.markdown import hbold
from aiohttp import ClientConnectorError
from aiogram.filters import Command, BaseFilter
from ..kb import changer_panel_bottom
from ..models import Req, Invoice, Course, ReqUsage, TGUser, Country, WithdrawalMode, Shop, ShopOperator
from asgiref.sync import sync_to_async
from django.db.models.functions import Coalesce
from django.db.models import Sum, Count, F, Q, FloatField
from datetime import date
import asyncio
from django.utils import timezone
from datetime import timedelta, datetime
from ..text import main_page_text, add_new_req_text, order_operator_text

PAGE_SIZE = 30
async def find_req(amount_usd):
    today = date.today()
    valid_reqs = await sync_to_async(lambda: Req.objects.filter(active=True, user__limit__gte=amount_usd, archived=False).annotate(
        usage_count=Count('requsage',filter=Q(requsage__date_used__date=today))).order_by('usage_count'))()

    for req in valid_reqs:
        total_amount_val, awaiting_usdt = await balance_val(req.user)
        limit = req.user.limit - awaiting_usdt
        usage_balance = limit - total_amount_val
        if usage_balance >= amount_usd:
            total_amount_today = await check_daily_limit(req)
            usage_amount = req.limit - total_amount_today
            if usage_amount >= amount_usd:
                return req

async def check_daily_limit(req):
    today = date.today()
    total_amount_today = await sync_to_async(
        lambda: Invoice.objects.filter(
            req=req,
            accepted=True,
            date_used__date=today
        ).aggregate(
            total=Coalesce(Sum('amount_in_usdt'), 0, output_field=FloatField())
        )['total']
    )()
    return total_amount_today

async def promo_coder(promo, user, msg, bot):
    if promo.type == "new_changer":
        if promo.amount:
            user.limit += promo.amount
        user.is_changer = True
        user.save()
        reqs = await sync_to_async(Req.objects.filter)(user=user)
        if reqs:
            text = main_page_text.format(balance=user.balance, limit=user.limit)
            await msg.answer(text, reply_markup=changer_panel_bottom(user), parse_mode="Markdown")
        else:
            await req_adder(msg)
    elif promo.type == "new_shop":
        builder = InlineKeyboardBuilder()
        new_shop, created = await sync_to_async(Shop.objects.get_or_create)(boss=user)
        builder.add(InlineKeyboardButton(text="➕ Добавить Бизнес", callback_data="adding_new_shop"))
        await msg.answer("Добро пожаловать в систему платежей!", reply_markup=builder.as_markup())
    elif promo.type == "new_shop_operator":
        new_operator, created = await sync_to_async(ShopOperator.objects.get_or_create)(shop=promo.shop, operator=user)
        await msg.answer(f"Вы успешно добавлены!")

async def pay_checker(invoice, msg, bot, chat):
    new_req_usage = await sync_to_async(ReqUsage.objects.create)(usage_req=invoice.req, usage_inv=invoice,
                                                                 status="awaiting", chat=chat)
    secs = 0
    photo_sent = False
    timeout = False
    while True:
        try:
            invoice = await sync_to_async(Invoice.objects.get)(id=invoice.id)
            req_usage = await sync_to_async(ReqUsage.objects.get)(id=new_req_usage.id)
            if invoice.status == "deleted":
                new_req_usage.status = "timeout"
                new_req_usage.active = False
                await sync_to_async(new_req_usage.save)()
                break
            if req_usage.status == "photo_sent" and not photo_sent:
                photo_sent = True
            if secs >= 1200 and not timeout:
                new_req_usage.status = "timeout"
                new_req_usage.active = False
                timeout = True
                await sync_to_async(new_req_usage.save)()
            if secs >= 5000:
                break
            if invoice.accepted:
                await msg.answer("✅")
                new_req_usage.status = "finish"
                new_req_usage.active = False
                await sync_to_async(new_req_usage.save)()
                changer = invoice.req.user
                usage_reqs = await sync_to_async(ReqUsage.objects.filter)(active=True, usage_req__user=changer)
                if not await sync_to_async(usage_reqs.exists)():
                    total_amount_val, awaiting_usdt  = await balance_val(changer)
                    val_in_usdt = total_amount_val + awaiting_usdt
                    ostatok = changer.limit - val_in_usdt
                    if ostatok <= 25:
                        await req_inactive(changer)
                        await bot.send_message(chat_id=changer.user_id, text="Режим P2P отключен\n\n❗️ Для завершения круга перейдите в раздел P2P",
                                                   reply_markup=await changer_panel_bottom(changer))


                break
        except Exception as e:
            print(e)
        await asyncio.sleep(30)
        secs += 30


async def balance_val(user):
    total_amount_val = await sync_to_async(lambda: Invoice.objects.filter(accepted=True, sent_bank=False,
                                                                          req__user=user).aggregate(
        total=Coalesce(Sum('amount_in_usdt_for_changer'), 0,
                       output_field=FloatField()))['total'])()

    awaiting_usdt = await sync_to_async(
        lambda: ReqUsage.objects.filter(active=True, usage_req__user=user).aggregate(
            total=Coalesce(Sum('usage_inv__amount_in_usdt'), 0, output_field=FloatField()))['total'])()
    return total_amount_val, awaiting_usdt

async def changers_current_balance(user):
    total_amount_val = await sync_to_async(lambda: Invoice.objects.filter(accepted=True, sent_bank=True,
                                                                          req__user=user, sent_changer=False).aggregate(
        total=Coalesce(Sum('amount_in_usdt_for_changer'), 0,
                       output_field=FloatField()))['total'])()
    balance = total_amount_val / 100 * user.prc
    ref_val = await sync_to_async(lambda: Invoice.objects.filter(accepted=True, sent_bank=True,
                                                                          req__user__ref_by=user, sent_ref=False).aggregate(
        total=Coalesce(Sum('amount_in_usdt_for_changer'), 0,
                       output_field=FloatField()))['total'])()
    ref_balance = ref_val / 100 * 2
    return balance, ref_balance

async def changer_balance_with_invoices(user):
    usdt_balance, main_invoice_list = await sync_to_async(lambda: (
        Invoice.objects.filter(accepted=True, sent_bank=True, req__user=user, sent_changer=False)
        .aggregate(total=Coalesce(Sum('amount_in_usdt_for_changer'), 0.0, output_field=FloatField()))['total'],
        list(Invoice.objects.filter(accepted=True, sent_bank=True, req__user=user, sent_changer=False))
    ))()
    print("IN changer_balance_with_invoices, MAIN INVS", main_invoice_list)
    ref_balance, ref_invoice_list = await sync_to_async(lambda: (
        Invoice.objects.filter(accepted=True, sent_bank=True, req__user__ref_by=user, sent_ref=False)
        .aggregate(total=Coalesce(Sum('amount_in_usdt_for_changer'), 0.0, output_field=FloatField()))['total'],
        list(Invoice.objects.filter(accepted=True, sent_bank=True, req__user__ref_by=user, sent_ref=False))
    ))()

    balance = usdt_balance / 100 * user.prc
    ref_balance = ref_balance / 100 * 2

    return balance, main_invoice_list, ref_balance, ref_invoice_list


async def req_inactive(user):
    reqs = await sync_to_async(Req.objects.filter)(active=True, user=user)
    for req in reqs:
        req.active = False
        await sync_to_async(req.save)()
    return True


# async def req_activater(user, msg):
#     total_amount_val, awaiting_usdt = await balance_val(user)
#     val_in_usdt = total_amount_val + awaiting_usdt
#     ostatok = user.limit - val_in_usdt
#     if ostatok > 25:
#         reqs = await sync_to_async(Req.objects.filter)(user=user)
#         for req in reqs:
#             req.active = True
#             await sync_to_async(req.save)()
#         return True
#     else:
#         text = (f"   🧮 {hbold('Валидная сумма')}: {hbold(f'${round(ostatok, 2)}')}\n\n"
#                      f"\n❗️ Включить P2P режим не удалось!")
#
#         await msg.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
#         return False

async def inactivity_checker(bot):
    while True:
        now = timezone.now()
        inactive_threshold = now - timedelta(minutes=30)
        users_to_notify = await sync_to_async(TGUser.objects.filter)(
            last_active__lt=inactive_threshold,
            is_changer=True
        )

        for user in users_to_notify:
            try:
                reqs = await sync_to_async(Req.objects.filter)(active=True, user=user)
                if reqs:
                    if not user.inactive_notified:
                        # await bot.send_message(chat_id=user.user_id, text="😴 Мы давно вас не видели, вы с нами?")
                        user.inactive_notified = True
                        user.inactive_notified_at = now
                        await sync_to_async(user.save)()
                    else:
                        if user.inactive_notified_at and (now - user.inactive_notified_at) > timedelta(hours=1):
                            result = req_inactive(user)
                            user.inactive_notified = False
                            user.inactive_notified_at = None
                            await sync_to_async(user.save)()
            except Exception as e:
                print(f"Ошибка при обработке пользователя {user.user_id}: {e}")
        await asyncio.sleep(60)


async def req_adder(msg):
    countries = await sync_to_async(Country.objects.all)()
    builder = InlineKeyboardBuilder()
    for country in countries:
        builder.add(InlineKeyboardButton(text=f"{country.flag} {country.country.upper()}", callback_data=f"add_new_req_{country.id}"))
    builder.adjust(2)
    await msg.answer(add_new_req_text, reply_markup=builder.as_markup())


@sync_to_async
def get_totals_reqs(req):
    queryset = Invoice.objects.filter(accepted=True, sent_bank=False, req=req)
    totals = queryset.aggregate(
        total_usdt=Coalesce(Sum('amount_in_usdt_for_changer'), 0.0, output_field=FloatField()),
        total_fiat=Coalesce(Sum('amount_in_fiat'), 0.0, output_field=FloatField()),
    )
    return totals


async def get_ltc_usd_rate():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=usd"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
                return data["litecoin"]["usd"]
    except Exception as e:
        print("Ошибка при получении курса LTC/USD:", e)
        return None


async def create_ltc_invoice(amount_usd):
    account = os.getenv("APIRONE_ACC")
    create_invoice_url = f'https://apirone.com/api/v2/accounts/{account}/invoices'

    course = await get_ltc_usd_rate()
    if course is not None:
        ltc_amount = float(amount_usd) / float(course)
        decimal_places = 8
        amount_in_microunits = int(ltc_amount * 10 ** decimal_places)

        invoice_data = {
            "amount": amount_in_microunits,
            "currency": "ltc",
            "lifetime": 43200,
            "callback_url": "http://example.com/callback",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                        create_invoice_url,
                        json=invoice_data,
                        headers={'Content-Type': 'application/json'}
                ) as response:
                    invoice_info = await response.json()
            return invoice_info, ltc_amount
        except ClientConnectorError:
            return await create_ltc_invoice(amount_usd)
    else:
        return None, None

async def create_limit_invoice():
    account = os.getenv("APIRONE_ACC")
    create_invoice_url = f'https://apirone.com/api/v2/accounts/{account}/invoices'
    course = await get_ltc_usd_rate()
    amount_usd = 50
    if course is not None:
        ltc_amount = float(amount_usd) / float(course)
        decimal_places = 8
        amount_in_microunits = int(ltc_amount * 10 ** decimal_places)

        invoice_data = {
            "amount": amount_in_microunits,
            "currency": "ltc",
            "lifetime": 43200,
            "lifetime": 43200,
            "callback_url": "http://example.com/callback",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                        create_invoice_url,
                        json=invoice_data,
                        headers={'Content-Type': 'application/json'}
                ) as response:
                    invoice_info = await response.json()
            return invoice_info, ltc_amount
        except ClientConnectorError:
            return await create_ltc_invoice(amount_usd)
    else:
        return None, None

async def check_invoice(wid, invoice_id, bot):
    pack = await sync_to_async(WithdrawalMode.objects.get)(id=wid)
    balance_plus = 0
    part_paid = False
    while True:
        url = f"https://apirone.com/api/v2/invoices/{invoice_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as res:
                    if res.status == 200:
                        invoice_data = await res.json()
                        for i in invoice_data['history']:
                            if i['status'] == 'partpaid' and not part_paid:
                                total_crypto = float(invoice_data['amount']) / 1_000_000
                                paid_crypto = float(i['amount']) / 1_000_000
                                left_crypto = total_crypto - paid_crypto
                                await bot.send_message(chat_id=pack.user.user_id, text=f"Необходимо доплатить {left_crypto} LTC\n{invoice_data['address']}")
                                part_paid = True
                        if invoice_data['status'] == 'completed' or invoice_data['status'] == 'overpaid':
                            invoices = pack.invoices.all()
                            for invoice in invoices:
                                invoice.sent_bank = True
                                invoice.save()
                                prc = pack.user.prc
                                balance_plus += invoice.amount_in_usdt_for_changer / 100 * prc
                            await bot.send_message(chat_id=pack.user.user_id, text=f"💸 Баланс пополнен на ${balance_plus}")
                            pack.active = False
                            pack.finish = True
                            pack.save()
                            break
                        if invoice_data['status'] == 'expired':
                            pack.active = False
                            pack.save()
                            await bot.send_message(chat_id=pack.user.user_id, text=f"😔 Время просрочено, создайте заявку заново.")
                            break
                    await asyncio.sleep(60)
        except Exception as e:
            print(e)

async def check_limit_invoice(wid, invoice_id, bot):
    pack = await sync_to_async(WithdrawalMode.objects.get)(id=wid)
    while True:
        url = f"https://apirone.com/api/v2/invoices/{invoice_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as res:
                    if res.status == 200:
                        invoice_data = await res.json()
                        if invoice_data['status'] == 'completed' or invoice_data['status'] == 'overpaid':
                            pack.user.limit += 50
                            pack.user.save()
                            await bot.send_message(chat_id=pack.user.user_id,
                                                       text=f"💸 Лимит увеличен на $50")
                            pack.active = False
                            pack.finish = True
                            pack.save()
                            break
                        if invoice_data['status'] == 'expired':
                            pack.active = False
                            pack.save()
                            await bot.send_message(chat_id=pack.user.user_id,
                                                       text=f"😔 Время просрочено, создайте заявку заново.")
                            break
                    await asyncio.sleep(60)
        except Exception as e:
            print(e)

async def shop_balance(shop):
    shop_bal, shop_invoices = await sync_to_async(lambda: (
        Invoice.objects.filter(accepted=True, sent_shop=False, shop=shop)
        .aggregate(total=Coalesce(Sum('amount_in_usdt'), 0.0, output_field=FloatField()))['total'],
        list(Invoice.objects.filter(accepted=True, sent_shop=False, shop=shop))
    ))()
    return shop_bal, shop_invoices

async def admin_balance(user):
    if user.is_admin:
        admin_bal, admin_invoices = await sync_to_async(lambda: (
            Invoice.objects.filter(accepted=True, sent_admin=False)
            .aggregate(total=Coalesce(Sum('amount_in_usdt_for_changer'), 0.0, output_field=FloatField()))['total'],
            list(Invoice.objects.filter(accepted=True, sent_admin=False))
        ))()
        admin_bal = admin_bal / 100 * 1
        return admin_bal, admin_invoices

async def transfer(satoshi, ltc_req, wid):
    transfer_key = os.getenv("TRANSFER_KEY")
    account = os.getenv("APIRONE_ACC")
    url = f"https://apirone.com/api/v2/accounts/{account}/transfer"

    headers = {'Content-Type': 'application/json'}
    payload = {
        "currency": "ltc",
        "transfer-key": transfer_key,
        "destinations": [{"address": ltc_req,"amount": satoshi}],
        "fee": "normal",
        "subtract-fee-from-amount": False
    }
    pack = await sync_to_async(WithdrawalMode.objects.get)(id=wid)
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as response:
            if response.status == 200:
                result = await response.json()
                print(result)
                invoices = pack.invoices.all()
                print("INVOICES", invoices)
                if invoices:
                    for i in invoices:
                        print("in SENT CHANGER")
                        i.sent_changer = True
                        await sync_to_async(i.save)()
                ref_invoices = pack.ref_invoices.all()
                if ref_invoices:
                    for i in ref_invoices:
                        i.sent_ref = True
                        i.save()
                pack.finish = True
                pack.active = False
                pack.save()
                result = await format_transfer_result(result)
                print("RESULT AFTER FORMAT", result)
                return result
            else:
                pack.active = False
                pack.save()
                print(f"Failed transfer. Status code: {response.status}")
                error_message = await response.text()
                print("Error message:", error_message)
                return error_message

async def transfer_to_shop(satoshi, ltc_req, wid):
    transfer_key = os.getenv("TRANSFER_KEY")
    account = os.getenv("APIRONE_ACC")
    url = f"https://apirone.com/api/v2/accounts/{account}/transfer"

    headers = {'Content-Type': 'application/json'}
    payload = {
        "currency": "ltc",
        "transfer-key": transfer_key,
        "destinations": [{"address": ltc_req, "amount": satoshi}],
        "fee": "normal",
        "subtract-fee-from-amount": False
    }
    pack = await sync_to_async(WithdrawalMode.objects.get)(id=wid)
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as response:
            if response.status == 200:
                result = await response.json()
                print("Transfer successful:", result)
                invoices = pack.invoices.all()
                if invoices:
                    for i in invoices:
                        i.sent_shop = True
                        i.save()
                pack.active = False
                pack.finish = True
                pack.save()
                result = await format_transfer_result(result)
                return result
            else:
                pack.active = False
                pack.save()
                print(f"Failed transfer. Status code: {response.status}")
                error_message = await response.text()
                print("Error message:", error_message)
                return error_message

async def transfer_to_admin(satoshi, ltc_req, wid):
    transfer_key = os.getenv("TRANSFER_KEY")
    account = os.getenv("APIRONE_ACC")
    url = f"https://apirone.com/api/v2/accounts/{account}/transfer"

    headers = {'Content-Type': 'application/json'}
    payload = {
        "currency": "ltc",
        "transfer-key": transfer_key,
        "destinations": [{"address": ltc_req, "amount": satoshi}],
        "fee": "normal",
        "subtract-fee-from-amount": False
    }
    pack = await sync_to_async(WithdrawalMode.objects.get)(id=wid)
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as response:
            if response.status == 200:
                result = await response.json()
                print("Transfer successful:", result)
                invoices = pack.invoices.all()
                if invoices:
                    for i in invoices:
                        i.sent_admin = True
                        i.save()
                pack.active = False
                pack.finish = True
                pack.save()
                result = await format_transfer_result(result)
                return result
            else:
                pack.active = False
                pack.save()
                print(f"Failed transfer. Status code: {response.status}")
                error_message = await response.text()
                print("Error message:", error_message)
                return error_message

async def format_transfer_result(data: dict) -> str:
    try:
        destinations = data.get('destinations', [])
        if not destinations:
            return "❌ Ошибка: нет данных о переводе."

        dest = destinations[0]
        address = dest.get('address', 'Неизвестно')
        amount_satoshi = dest.get('amount', 0)
        amount_ltc = amount_satoshi / 100_000_000  # сатоши в LTC

        text = (
            f"✅ Переведено **{amount_ltc:.8f} LTC**\n"
            f"📍 На адрес: `{address}`"
        )
        return text
    except Exception as e:
        return f"❌ Ошибка обработки данных перевода: {e}"

async def operator_invoices(operator):
    shop_operator = await sync_to_async(ShopOperator.objects.get)(operator=operator)
    usdt_balance, invoice_list = await sync_to_async(lambda: (
        Invoice.objects.filter(accepted=True, shop=shop_operator.shop)
        .aggregate(total=Coalesce(Sum('amount_in_usdt'), 0.0, output_field=FloatField()))['total'],
        list(Invoice.objects.filter(accepted=True, shop=shop_operator.shop))
    ))()
    return usdt_balance, invoice_list

async def req_invoices(req):
    usdt_balance, invoice_list = await sync_to_async(lambda: (
        Invoice.objects.filter(accepted=True, req=req)
        .aggregate(total=Coalesce(Sum('amount_in_usdt'), 0.0, output_field=FloatField()))['total'],
        list(Invoice.objects.filter(accepted=True, req=req))
    ))()
    return usdt_balance, invoice_list


class IsLTCReq(BaseFilter):
    async def call(self, msg: Message) -> bool:
        try:
            if msg.text:
                req = msg.text
                traditional_pattern = r'^[L3][A-Za-z0-9]{26,33}$'
                bech32_pattern = r'^ltc1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{39,59}$'
                p2sh_pattern = r'^M[A-Za-z0-9]{26,33}$'

                return any([
                    re.match(traditional_pattern, req),
                    re.match(bech32_pattern, req),
                    re.match(p2sh_pattern, req)
                ])
        except Exception as e:
            return False

async def IsLtcReq(req):
    traditional_pattern = r'^[L3][A-Za-z0-9]{26,33}$'
    bech32_pattern = r'^ltc1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{39,59}$'
    p2sh_pattern = r'^M[A-Za-z0-9]{26,33}$'

    return any([
        re.match(traditional_pattern, req),
        re.match(bech32_pattern, req),
        re.match(p2sh_pattern, req)
    ])

async def operator_mode_invoice_balances(invoices):
    balance = 0
    for inv in invoices:
        balance += inv.amount_in_usdt
    return round(balance, 2)