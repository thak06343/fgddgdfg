from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from datetime import datetime
from typing import Callable, Awaitable
from .models import TGUser
from asgiref.sync import sync_to_async
from datetime import datetime, timedelta
from django.utils import timezone



class ActivityLoggerMiddleware(BaseMiddleware):
    async def __call__(self,
                       handler: Callable[[TelegramObject, dict], Awaitable],
                       event: TelegramObject,
                       data: dict):
        try:
            user = data.get("event_from_user")
            if user:
                await self.log_user_activity(user)
        except Exception as e:
            print(f"[MIDDLEWARE ERROR]: {e}")
        return await handler(event, data)

    @sync_to_async
    def log_user_activity(self, user):
        now = timezone.now()
        tg_user, created = TGUser.objects.get_or_create(user_id=str(user.id))

        was_inactive = False
        if not created and tg_user.last_active and (now - tg_user.last_active) > timedelta(minutes=30):
            was_inactive = True

        tg_user.first_name = user.first_name
        tg_user.last_name = user.last_name
        tg_user.username = user.username
        tg_user.last_active = now

        if was_inactive:
            tg_user.inactive_notified = False
        tg_user.save()
