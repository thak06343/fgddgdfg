from django.contrib import admin
from .models import TGUser, Invoice, Req, ReqUsage, OperatorClientChat, Course, ShopOperator, Shop, Promo, Country, WithdrawalMode, ApiAccount


@admin.register(TGUser)
class TGUserAdmin(admin.ModelAdmin):
    list_display = ['id', 'username' if 'username' else 'first_name']


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['id']

@admin.register(ApiAccount)
class ApiAccountAdmin(admin.ModelAdmin):
    list_display = ['id']

@admin.register(Req)
class ReqAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'active', 'archived', 'cart']

@admin.register(ReqUsage)
class ReqUsageAdmin(admin.ModelAdmin):
    list_display = ['id', 'active', 'status']

@admin.register(OperatorClientChat)
class OperatorClientChatAdmin(admin.ModelAdmin):
    list_display = ['id', 'operator']

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['id', 'shop']


@admin.register(ShopOperator)
class ShopOperatorAdmin(admin.ModelAdmin):
    list_display = ['id', 'shop', 'operator']

@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'boss']

@admin.register(Promo)
class PromoAdmin(admin.ModelAdmin):
    list_display = ['id']

@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ['id', 'country', 'flag']

@admin.register(WithdrawalMode)
class WithdrawalModeAdmin(admin.ModelAdmin):
    list_display = ['id', 'active', 'finish', 'user', 'ltc_amount']