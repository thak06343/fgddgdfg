from django.contrib import admin
from .models import TGUser, Invoice, Req, ReqUsage, OperatorClientChat, Course, ShopOperator, Shop, Promo, Country, WithdrawalMode


@admin.register(TGUser)
class TGUserAdmin(admin.ModelAdmin):
    list_display = ['id', 'username' if 'username' else 'first_name']


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['id']


@admin.register(Req)
class ReqAdmin(admin.ModelAdmin):
    list_display = ['id']

@admin.register(ReqUsage)
class ReqUsageAdmin(admin.ModelAdmin):
    list_display = ['id', 'active', 'status']

@admin.register(OperatorClientChat)
class OperatorClientChatAdmin(admin.ModelAdmin):
    list_display = ['id']

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['id']


@admin.register(ShopOperator)
class ShopOperatorAdmin(admin.ModelAdmin):
    list_display = ['id']

@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ['id']

@admin.register(Promo)
class PromoAdmin(admin.ModelAdmin):
    list_display = ['id']

@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ['id']

@admin.register(WithdrawalMode)
class WithdrawalModeAdmin(admin.ModelAdmin):
    list_display = ['id', 'active', 'finish', 'user', 'ltc_amount']