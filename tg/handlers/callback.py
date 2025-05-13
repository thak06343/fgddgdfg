from aiogram.filters.callback_data import CallbackData

class InvoicePagination(CallbackData, prefix="inv"):
    page: int
