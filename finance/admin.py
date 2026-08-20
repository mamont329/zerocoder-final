from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import Category, Profile, Transaction, purge_user


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


class UserWithDataAdmin(UserAdmin):
    """Удаление пользователя в админке — тем же путём, что и на сайте."""

    def delete_model(self, request, obj):
        purge_user(obj)

    def delete_queryset(self, request, queryset):
        for user in queryset:
            purge_user(user)


admin.site.unregister(User)
admin.site.register(User, UserWithDataAdmin)
