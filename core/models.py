"""
Data models for PnL Rosabella web app.
Dates stored as DateField (no time) — eliminates all TZ ambiguity.
"""
from decimal import Decimal
from django.db import models


class COGSItem(models.Model):
    """SKU cost lookup table — supplier-verified per-order cost."""
    sku_id = models.CharField(max_length=32, unique=True, db_index=True)
    product_name = models.CharField(max_length=255, blank=True)
    sku_variant = models.CharField(max_length=128, blank=True)
    cogs_per_order = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    supplier_ref = models.CharField(max_length=64, blank=True)
    listing_id = models.CharField(max_length=32, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    approval = models.CharField(max_length=32, blank=True, default='Y')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.sku_id} — {self.product_name[:40]}"

    class Meta:
        ordering = ['supplier_ref']


class Order(models.Model):
    """One row per (Order ID, SKU ID) line from Manage Orders CSV."""
    order_id = models.CharField(max_length=32, db_index=True)
    sku_id = models.CharField(max_length=32, db_index=True)
    created_date = models.DateField(db_index=True)
    quantity = models.IntegerField(default=0)
    status = models.CharField(max_length=32, blank=True)
    gross_sale = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    seller_discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cogs = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    source_file = models.CharField(max_length=255, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('order_id', 'sku_id')]
        indexes = [models.Index(fields=['created_date'])]


class SettlementRow(models.Model):
    """One row per (Order ID, Settlement ID, Type) from settlement export."""
    order_created_date = models.DateField(db_index=True, null=True)
    statement_date = models.DateField(null=True)
    order_id = models.CharField(max_length=32, db_index=True)
    settlement_id = models.CharField(max_length=32)
    row_type = models.CharField(max_length=64, db_index=True)
    quantity = models.IntegerField(default=0)

    referral_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    affiliate_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    campaign_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    refund_admin = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fbt_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fbt_reimb = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tt_ship_net = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tt_shop_shipping_incentive = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_fee_subsidy = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    customer_shipping_fee_offset = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    customer_paid_shipping_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    customer_paid_shipping_refund = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cofunded_promo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cofunded_promo_campaign_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    seller_shipping_fee_discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    refund_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    chargeback = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    violation = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tt_shop_reimb = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    logistics_reimb = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fbt_warehouse = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fbt_warehouse_comp = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    rebate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unclassified = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    source_file = models.CharField(max_length=255, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('order_id', 'settlement_id', 'row_type')]
        indexes = [
            models.Index(fields=['order_created_date']),
            models.Index(fields=['row_type']),
        ]


class SellerShipmentCost(models.Model):
    """One row per shipment from seller-shipping CSV (3PL postage + pack/pick breakdown).
    Primary key is shipment_number — re-imports dedup on it.
    `order_date` is the day the customer placed the order (accrual basis); `shipped_date`
    is the day the package left the warehouse. Aggregator prefers order_date when present."""
    shipment_number = models.CharField(max_length=128, unique=True, db_index=True)
    order_date = models.DateField(db_index=True, null=True, blank=True)
    shipped_date = models.DateField(db_index=True)
    postage = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    per_pack = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    per_pick = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    product_quantity = models.IntegerField(default=0)
    reference_number = models.CharField(max_length=128, blank=True)
    customer_name = models.CharField(max_length=128, blank=True)
    carrier_service = models.CharField(max_length=64, blank=True)
    tracking = models.CharField(max_length=128, blank=True)
    channel_name = models.CharField(max_length=64, blank=True)
    source_file = models.CharField(max_length=255, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)


class AnalyticsDay(models.Model):
    """Daily GMV from Shop Analytics export."""
    date = models.DateField(unique=True)
    gmv = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    orders = models.IntegerField(default=0)
    items_sold = models.IntegerField(default=0)


class AdSpendDay(models.Model):
    """Daily ad spend from TikTok Ads Manager export."""
    date = models.DateField(unique=True)
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sku_orders = models.IntegerField(default=0)
    gross_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)


class MonthlyInput(models.Model):
    """One row per yyyy-mm with manual + FBT-billing values."""
    month = models.CharField(max_length=7, unique=True, help_text="YYYY-MM")

    team_spend = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    software_tools = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    monthly_retainers = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    creatify = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    off_platform_1pct = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_ga = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tt_promo_credits = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cost_ship_to_fbt = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cost_ship_to_customer = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    fbt_hub_placement = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fbt_storage = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fbt_inbound_shipping = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fbt_inbound_incidents = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fbt_booking_noncomp = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fbt_routing_noncomp = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fbt_outbound_noshow = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fbt_delayed_response = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fbt_disposal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fbt_return_shipping = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fbt_return_seller_handling = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fbt_inbound_return_op = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['month']

    def __str__(self):
        return self.month


class MonthlyInputAudit(models.Model):
    """One row per field-change on MonthlyInput. Lets us show 'what was changed when' history."""
    month = models.CharField(max_length=7, db_index=True)
    field_name = models.CharField(max_length=64)
    old_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    new_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-changed_at']


class AdTransaction(models.Model):
    """One row per transaction line from TikTok Ads Manager → Transactions export.
    Three sheets feed this table: Payments (card charges), Promotions (free + agency promos),
    Others (TBSM agency 'Increase balance' loads)."""
    txn_id = models.CharField(max_length=64, blank=True, db_index=True)
    txn_time = models.DateTimeField(db_index=True)
    sheet = models.CharField(max_length=16, db_index=True)
    txn_type = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=32, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    details = models.CharField(max_length=255, blank=True)
    type_label = models.CharField(max_length=64, blank=True)
    source_file = models.CharField(max_length=255, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('txn_id', 'sheet', 'txn_time', 'amount')]
        indexes = [models.Index(fields=['txn_time'])]


class AgencyPromoTag(models.Model):
    """Tag a Promotions-sheet day as agency-purchased at a specific discount rate
    (e.g. KDMT $300k delivered as promos at 10%). Promos NOT tagged here default to free."""
    date = models.DateField(db_index=True)
    min_amount = models.DecimalField(max_digits=12, decimal_places=2, default=10000,
        help_text="Only the daily-net promo total >= this amount gets tagged; smaller promos stay free.")
    discount_pct = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.10'))
    note = models.CharField(max_length=128, blank=True)

    class Meta:
        ordering = ['date']
        unique_together = [('date',)]


class AgencyInvoice(models.Model):
    """Manual list of agency invoices for cross-reference against TikTok loads."""
    invoice_no = models.CharField(max_length=64, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    loaded_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.06'))
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    entity = models.CharField(max_length=128, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-issue_date']


class AdLedgerConfig(models.Model):
    """Singleton (pk=1) config for the FIFO ad ledger engine."""
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0,
        help_text="Account balance carried into the start date (pre-window credit).")
    opening_date = models.DateField(null=True, blank=True,
        help_text="Date the opening balance applies as-of.")
    opening_discount = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.06'))
    tbsm_default_discount = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.06'),
        help_text="Discount applied to every Others/Increase balance load by default.")
    feed_pnl = models.BooleanField(default=False,
        help_text="When True, AdLedgerDay TBSM Savings + TT Promo Credits override the "
                  "manual/zero values on Daily and Monthly P&L. Keep False until the engine "
                  "is verified against the source exports.")
    updated_at = models.DateTimeField(auto_now=True)


class AdLedgerDay(models.Model):
    """Computed daily snapshot from the FIFO ledger engine."""
    date = models.DateField(unique=True)
    ad_spend = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tbsm_in = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    promo_in = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    card_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    closing_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    funded = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    full_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    savings_tbsm = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    savings_promo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    actual_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    funding_source = models.CharField(max_length=64, blank=True)
    discount_on_funded = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    effective_discount = models.DecimalField(max_digits=6, decimal_places=4, default=0)

    class Meta:
        ordering = ['date']


class ImportLog(models.Model):
    """Audit trail — what was uploaded when."""
    importer = models.CharField(max_length=32)
    filename = models.CharField(max_length=255)
    rows_added = models.IntegerField(default=0)
    rows_skipped = models.IntegerField(default=0)
    notes = models.TextField(blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-imported_at']
