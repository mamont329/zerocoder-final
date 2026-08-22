from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import (BotDialog, Category, MaintenanceRun, NotificationLog, Profile,
                     SavedReport, Transaction, purge_user)


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


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ('sent_at', 'user', 'kind', 'key')
    list_filter = ('kind', 'sent_at')
    readonly_fields = ('sent_at',)


@admin.register(SavedReport)
class SavedReportAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'period', 'type', 'category')
    list_filter = ('period', 'type')
    search_fields = ('name',)


@admin.register(BotDialog)
class BotDialogAdmin(admin.ModelAdmin):
    list_display = ('key', 'state', 'updated_at')
    readonly_fields = ('updated_at',)


@admin.register(MaintenanceRun)
class MaintenanceRunAdmin(admin.ModelAdmin):
    list_display = ('started_at', 'title', 'status', 'started_by')
    list_filter = ('status',)
    readonly_fields = ('started_at', 'finished_at')


class UserWithDataAdmin(UserAdmin):
    """Удаление пользователя в админке — тем же путём, что и на сайте."""

    def delete_model(self, request, obj):
        purge_user(obj)

    def delete_queryset(self, request, queryset):
        for user in queryset:
            purge_user(user)


admin.site.unregister(User)
admin.site.register(User, UserWithDataAdmin)
