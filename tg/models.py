from django.db import models
from django.utils import timezone
import uuid


class TGUser(models.Model):
    user_id = models.CharField(max_length=255)
    first_name = models.CharField(max_length=255, null=True, blank=True)
    last_name = models.CharField(max_length=255, null=True, blank=True)
    username = models.CharField(max_length=255, null=True, blank=True)
    is_changer = models.BooleanField(default=False)
    is_admin = models.BooleanField(default=False)
    is_super_admin = models.BooleanField(default=False)
    ref_by = models.ForeignKey("TGUser", on_delete=models.SET_NULL, null=True, blank=True)
    referral_code = models.CharField(max_length=255, null=True, blank=True)
    balance = models.FloatField(default=0)
    limit = models.FloatField(default=0)
    prc = models.FloatField(default=4)
    last_active = models.DateTimeField(default=timezone.now, null=True, blank=True)
    inactive_notified = models.BooleanField(default=False)
    inactive_notified_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.referral_code:
            self.referral_code = self.generate()
        super().save(*args, **kwargs)

    def generate(self):
        return str(uuid.uuid4().hex[:10]).upper()



    def __str__(self):
        return self.username if self.username else f'{self.first_name} {self.last_name}'


class Shop(models.Model):
    name = models.CharField(max_length=255, null=True, blank=True)
    crypto_req = models.CharField(max_length=2555, null=True, blank=True)
    boss = models.ForeignKey(TGUser, on_delete=models.SET_NULL, null=True, blank=True)
    prc = models.FloatField(default=13.5, null=True, blank=True)

    def __str__(self):
        return f"{self.name} {self.boss}"


class ShopOperator(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.SET_NULL, null=True, blank=True)
    operator = models.ForeignKey(TGUser, on_delete=models.SET_NULL, null=True, blank=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.shop} {self.operator} {self.active}"


class Req(models.Model):
    user = models.ForeignKey(TGUser, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=255, null=True, blank=True)
    active = models.BooleanField(default=True)
    cart = models.CharField(max_length=255)
    limit = models.FloatField(default=400)
    archived = models.BooleanField(default=False)
    country = models.ForeignKey("Country", on_delete=models.SET_NULL, null=True, blank=True)
    info = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.user} {self.name} {self.cart} {self.country}"


class OperatorClientChat(models.Model):
    chat_id = models.CharField(max_length=255)
    operator = models.ForeignKey(TGUser, on_delete=models.SET_NULL, null=True, blank=True, related_name="chat_operator")
    client = models.ForeignKey(TGUser, on_delete=models.SET_NULL, null=True, blank=True, related_name="chat_client")

    def __str__(self):
        return f"{self.operator} {self.client} {self.chat_id}"


class Invoice(models.Model):
    req = models.ForeignKey(Req, on_delete=models.SET_NULL, null=True, blank=True)
    amount_in_kzt = models.PositiveIntegerField()
    amount_in_usdt = models.FloatField()
    amount_in_fiat = models.FloatField(null=True, blank=True)
    amount_in_usdt_for_changer = models.FloatField(null=True, blank=True)
    date_used = models.DateTimeField(default=timezone.now)
    accepted = models.BooleanField(default=False)
    sent_bank = models.BooleanField(default=False)
    sent_shop = models.BooleanField(default=False)
    sent_changer = models.BooleanField(default=False)
    sent_sheff = models.BooleanField(default=False)
    sent_ref = models.BooleanField(default=False)
    sent_admin = models.BooleanField(default=False)
    status = models.CharField(max_length=255, null=True, blank=True)
    shop = models.ForeignKey(Shop, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.req} {self.amount_in_usdt} {self.status} {self.accepted}"


class ReqUsage(models.Model):
    usage_req = models.ForeignKey(Req, on_delete=models.SET_NULL, null=True, blank=True)
    usage_inv = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True)
    date_used = models.DateTimeField(default=timezone.now)
    chat = models.ForeignKey(OperatorClientChat, on_delete=models.SET_NULL, null=True, blank=True)
    photo = models.CharField(max_length=2555, null=True, blank=True)
    active = models.BooleanField(default=True)
    status = models.CharField(max_length=255)


class Course(models.Model):
    kzt_usd = models.FloatField(null=True, blank=True)


class Promo(models.Model):
    code = models.CharField(max_length=5, unique=True, null=True, blank=True)
    type = models.CharField(max_length=255)
    active = models.BooleanField(default=True)
    user = models.ForeignKey(TGUser, on_delete=models.SET_NULL, null=True, blank=True)
    amount = models.FloatField(null=True, blank=True)
    shop = models.ForeignKey(Shop, on_delete=models.SET_NULL, null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self.generate()
        super().save(*args, **kwargs)

    def generate(self):
        return str(uuid.uuid4().hex[:5]).upper()


class WithdrawalMode(models.Model):
    user = models.ForeignKey(TGUser, on_delete=models.SET_NULL, null=True, blank=True)
    invoices = models.ManyToManyField(Invoice, related_name="invoices", blank=True)
    ref_invoices = models.ManyToManyField(Invoice, related_name="ref_invoices", blank=True)

    ltc_amount = models.FloatField(null=True, blank=True)
    requisite = models.CharField(max_length=2555, null=True, blank=True)
    active = models.BooleanField(default=True)
    finish = models.BooleanField(default=False)


class Country(models.Model):
    country = models.CharField(max_length=255)
    flag = models.CharField(max_length=255, null=True, blank=True)
    kzt_to_fiat = models.FloatField()
    fiat_to_usdt = models.FloatField()
    fiat_to_usdt_for_shop = models.FloatField()

    def __str__(self):
        return self.country

class AnotherReq(models.Model):
    active = models.BooleanField(default=True)
    name = models.CharField(max_length=255)
    amount_in_usdt = models.FloatField()
    invoices_for_zp_cart = models.ManyToManyField(Invoice)
    one_time_req = models.BooleanField(default=False, null=True, blank=True)