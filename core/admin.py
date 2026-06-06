from django.contrib import admin
from .models import COGSItem, Order, SettlementRow, AnalyticsDay, AdSpendDay, MonthlyInput, ImportLog


@admin.register(COGSItem)
class COGSAdmin(admin.ModelAdmin):
    list_display = ('sku_id', 'product_name', 'sku_variant', 'cogs_per_order', 'supplier_ref', 'approval')
    list_editable = ('cogs_per_order',)
    search_fields = ('sku_id', 'product_name', 'supplier_ref')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_id', 'created_date', 'sku_id', 'quantity', 'status', 'gross_sale', 'cogs')
    list_filter = ('created_date', 'status')
    search_fields = ('order_id', 'sku_id')


@admin.register(SettlementRow)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ('order_created_date', 'statement_date', 'order_id', 'row_type', 'referral_fee', 'fbt_fee')
    list_filter = ('row_type', 'order_created_date')


@admin.register(MonthlyInput)
class MonthlyAdmin(admin.ModelAdmin):
    list_display = ('month', 'team_spend', 'monthly_retainers', 'fbt_hub_placement', 'updated_at')


@admin.register(ImportLog)
class LogAdmin(admin.ModelAdmin):
    list_display = ('imported_at', 'importer', 'filename', 'rows_added', 'rows_skipped')
    list_filter = ('importer',)


admin.site.register(AnalyticsDay)
admin.site.register(AdSpendDay)
