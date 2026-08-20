from django.contrib import admin

from .models import Category, Transaction


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
