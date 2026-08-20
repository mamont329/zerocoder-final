from django.contrib import admin

from .models import Category, Profile, Transaction


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'user', 'monthly_limit')
    list_filter = ('type', 'user')
    search_fields = ('name',)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('date', 'type', 'amount', 'category', 'user', 'description')
    list_filter = ('type', 'date', 'category')
    search_fields = ('description',)
    date_hierarchy = 'date'


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'telegram_id', 'daily_report')
    list_filter = ('daily_report',)
    readonly_fields = ('link_code',)
