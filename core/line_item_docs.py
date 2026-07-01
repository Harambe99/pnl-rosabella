"""Single source of truth for every P&L line item's meaning.

Used by:
  - The Monthly XLSX export ('Line Item Guide' sheet)
  - The README page

Each entry: {what, source, formula, notes}. Keep explanations short and
concrete — these get embedded in an exported file the boss may read.
"""

LINE_ITEM_DOCS = {
    # ============================ REVENUE ============================
    'Gross Sales': {
        'what': 'Pre-discount value of every order placed in this period.',
        'source': 'Manage Orders CSV → SKU Subtotal Before Discount (joined to Settlement via order_id).',
        'formula': 'Sum across ALL order statuses (Shipped, Completed, Canceled, To ship), attributed by the Statement date on the order\'s primary Settlement row.',
        'notes': 'Per Lindsay/Jack 2026-06-25 — orders attribute by Statement date (day TikTok processed the order through settlement), not by Created Time. Orders not yet settled don\'t appear until a fresh settlement file is uploaded. Includes canceled orders so the refund line nets them out.',
    },
    'Less: Promos & Discounts': {
        'what': 'Seller-funded discounts applied at order placement.',
        'source': 'Manage Orders CSV → SKU Seller Discount column (joined to Settlement via order_id).',
        'formula': 'Sum across all order statuses, attributed by the Statement date on the order\'s primary Settlement row. Stored negative.',
        'notes': 'Same Statement-date attribution as Gross Sales — moves in lockstep so GMV reconciles cleanly.',
    },
    'GMV': {
        'what': 'Gross Merchandise Value — the post-discount value of orders placed.',
        'source': 'Computed in-app.',
        'formula': 'Gross Sales + Less: Promos & Discounts.',
        'notes': 'Both inputs are on Statement-date methodology (settlement-period basis). Used as the GMV that drives Net Revenue.',
    },
    'GMV (TikTok Analytics — reference)': {
        'what': "TikTok's headline GMV from Shop Analytics, shown for comparison.",
        'source': 'Shop Analytics XLSX → GMV column.',
        'formula': 'Published by TikTok, not computed.',
        'notes': 'REFERENCE LINE ONLY — does NOT feed Net Revenue. Differs slightly from our computed GMV because TikTok applies internal filters (e.g., excludes certain order types, fraud filtering).',
    },
    'Less: Refunds': {
        'what': 'Refund impact on revenue from orders refunded after placement.',
        'source': 'Settlement XLSX → Gross sales refund + Seller discount refund.',
        'formula': 'sum(Gross sales refund) + sum(Seller discount refund), attributed by Statement date (the day TikTok processed the settlement).',
        'notes': 'Captures both pre-ship cancellation refunds and post-delivery returns. Stored negative.',
    },
    'NET REVENUE': {
        'what': 'Top-line revenue after discounts and refunds.',
        'source': 'Computed.',
        'formula': 'GMV + Less: Refunds.',
        'notes': 'All percentage columns elsewhere in the P&L are computed against this denominator.',
    },

    # ============================ COGS ============================
    'COGS': {
        'what': 'Cost of goods sold — the supplier cost of products fulfilled.',
        'source': 'Manage Orders × COGS table (per-SKU supplier cost).',
        'formula': 'sum(SKU quantity × COGS per unit) for orders that were either non-canceled OR canceled-but-shipped (identified via FBT fulfillment fee row in Settlement).',
        'notes': 'Post-ship cancellations retain COGS because the fulfillment cost was already incurred. Pre-ship cancellations correctly contribute $0.',
    },

    # ============================ FULFILLMENT — 7-line shipping bundle ============================
    'FBT Fulfillment Fee': {
        'what': 'TikTok\'s bundled pick/pack/ship fee for orders fulfilled via FBT.',
        'source': 'Settlement XLSX → FBT fulfillment fee column on Order rows.',
        'formula': 'sum(FBT fulfillment fee) by Statement date.',
        'notes': 'Sub-component of TikTok\'s Reports tab "Shipping" parent line. The 7 shipping lines below all sum to that parent.',
    },
    'FBT Fulfillment Reimbursement': {
        'what': 'TikTok refunding part or all of the FBT fee when fulfillment failed.',
        'source': 'Settlement XLSX → FBT fulfillment fee reimbursement column.',
        'formula': 'sum by Statement date. Positive (a credit back to you).',
        'notes': 'Fires when an FBT order had a fulfillment problem (lost, damaged, etc.).',
    },
    'TT Shop Shipping Incentive': {
        'what': 'TikTok\'s credit to seller when an order qualifies for free shipping.',
        'source': 'Settlement XLSX → TikTok Shop shipping incentive column.',
        'formula': 'sum by Statement date. Positive.',
        'notes': 'Almost always paired one-for-one with Customer Shipping Fee Offset (net seller impact: $0). Sub-component of Shipping parent.',
    },
    'TT Shop Shipping Incentive Refund': {
        'what': 'Clawback of a previously credited TT Shop Shipping Incentive.',
        'source': 'Settlement XLSX → TikTok Shop shipping incentive refund column.',
        'formula': 'sum by Statement date. Negative (reduces seller\'s net).',
        'notes': 'Pairs with TT Shop Shipping Incentive on the refund side. Per Jack 2026-06-30. Typically small (~$0-1.5k/month). Only populates after re-uploading Settlement files post the 0011 migration.',
    },
    'FBT Overall Merchant Subsidy': {
        'what': 'TikTok subsidy credited to the seller for FBT-related activity.',
        'source': 'Settlement XLSX → FBT overall merchant subsidy column.',
        'formula': 'sum by Statement date. Positive (credit to seller).',
        'notes': '8th sub-component of TikTok\'s Shipping parent aggregate — started firing in June 2026. Before that, this column was always $0. Only populates after re-uploading Settlement files post the 0012 migration.',
    },
    'Shipping Fee Subsidy': {
        'what': 'A separate subsidy program for seller-shipped orders.',
        'source': 'Settlement XLSX → Shipping fee subsidy column.',
        'formula': 'sum by Statement date.',
        'notes': 'Usually $0 — only fires when a specific seller subsidy program is active.',
    },
    'Customer Shipping Fee Offset': {
        'what': 'TikTok\'s clawback that mirrors the shipping incentive OR the customer-paid shipping fee.',
        'source': 'Settlement XLSX → Customer shipping fee offset column.',
        'formula': 'sum by Statement date. Negative.',
        'notes': 'Per TikTok docs: "typically used to offset either TikTok Shop\'s shipping incentive or customer-paid shipping fees, resulting in a net charge of $0 to you." The residual gap is seller-funded shipping on FBT-fulfilled products.',
    },
    'Customer-Paid Shipping Fee': {
        'what': 'Shipping fee the customer actually paid (orders under the free-shipping threshold).',
        'source': 'Settlement XLSX → Customer-paid shipping fee column.',
        'formula': 'sum by Statement date. Positive (revenue to seller).',
        'notes': 'On a shop with mostly free shipping, this is small. Sub-component of Shipping parent.',
    },
    'Customer-Paid Shipping Refund': {
        'what': 'Reversal of customer-paid shipping when an order is refunded.',
        'source': 'Settlement XLSX → Customer-paid shipping fee refund column.',
        'formula': 'sum by Statement date. Negative.',
        'notes': 'Pairs with Customer-Paid Shipping Fee on the refund side.',
    },
    # Seller Shipping Fee Discount removed 2026-06-30 — per Jack, the value is
    # already netted into the "Customer-paid shipping fee" column (NET) we book.
    # Booking it separately was double-counting the seller portion.

    # ============================ FULFILLMENT — non-Settlement shipping costs ============================
    'Cost to Ship to FBT': {
        'what': 'Inbound shipping cost — what YOU paid Jetpack (or any 3PL) to ship stock into the FBT warehouse.',
        'source': 'Monthly Input (manual entry — sum of Jetpack invoices).',
        'formula': '-1 × (monthly value ÷ days in services month). Flat-spread within the services month.',
        'notes': 'NOT on settlement-date methodology — this is a 3PL invoice you pay separately to Jetpack, outside TikTok\'s billing cycle, so it doesn\'t appear in the FBT Payment Cycle file. Stays flat-spread. (Confirmed exception with Lindsay 2026-06-26.)',
    },
    'Cost to Ship to Customer': {
        'what': 'Full outbound 3PL cost per shipment — postage + per-pack fee + per-pick fee.',
        'source': 'Seller Shipping CSV (3PL line-item report).',
        'formula': '-1 × sum(postage + per_pack + per_pick) grouped by Shipped Date.',
        'notes': 'Attributed by Shipped Date — the day Jetpack actually shipped the package — per Lindsay 2026-06-25. Stays consistent with the Settlement-date methodology used elsewhere on the P&L.',
    },

    # ============================ FULFILLMENT — Adjustments ============================
    'Logistics Reimbursement': {
        'what': 'TikTok refunding losses due to logistics-related issues or campaign participation.',
        'source': 'Settlement XLSX → Adjustment rows where Type = "Logistics reimbursement".',
        'formula': 'sum by Statement date. Positive.',
        'notes': 'Comes from the Adjustments parent in TikTok\'s Reports tab, not the Shipping parent.',
    },

    # ============================ FBT BILLING (TikTok-billed monthly fees) ============================
    # Each of these 12 lines is sourced from the FBT Billing XLSX (Logistics
    # Cost Overview) per services month. The month's days share the cost
    # equally so the daily P&L stays smooth (no day-1 spikes).
    # Reverted from settlement-date attribution back to services-month per
    # Jack 2026-07-01 — the FBT detail lands in the month the warehouse work
    # happened (matches TikTok's own billing period grouping).
    'FBT Hub Placement Fee': {
        'what': 'Cost charged by TikTok for placing your stock at FBT hub.',
        'source': 'FBT Billing XLSX (per-line $ per services month).',
        'formula': "-1 × (monthly value ÷ days in services month). Flat-spread within the services month the FBT work happened.",
        'notes': 'Services-month attribution per Jack 2026-07-01. FBT detail lines land in the month the warehouse work happened (matches TikTok\'s billing period grouping). Previously used settlement-date via Payment Cycle — reverted on Jack\'s request.',
    },
    'FBT Storage Fee': {
        'what': 'FBT warehouse storage fee.',
        'source': 'FBT Billing XLSX (per-line $ per services month).',
        'formula': "-1 × (monthly value ÷ days in services month). Flat-spread within the services month the FBT work happened. Destination month = month of TikTok's statement_date for the services period.",
        'notes': 'Services-month attribution per Jack 2026-07-01. Flat-spread within the services month.',
    },
    'FBT Inbound Shipping Fee': {
        'what': 'Inbound shipping fee TikTok charges when they arrange the inbound.',
        'source': 'FBT Billing XLSX (per-line $ per services month).',
        'formula': "-1 × (monthly value ÷ days in services month). Flat-spread within the services month the FBT work happened.",
        'notes': 'Usually $0 for shops that arrange their own inbound shipping. Services-month flat-spread per Jack 2026-07-01.',
    },
    'FBT Inbound Incidents Fee': {
        'what': 'Penalty fee for inbound shipment incidents (e.g., wrong labeling, damage).',
        'source': 'FBT Billing XLSX (per-line $ per services month).',
        'formula': "-1 × (monthly value ÷ days in services month). Flat-spread within the services month the FBT work happened.",
        'notes': 'Services-month flat-spread per Jack 2026-07-01.',
    },
    'FBT Booking Non-Compliance': {
        'what': 'Penalty fee when inbound booking rules aren\'t followed.',
        'source': 'FBT Billing XLSX (per-line $ per services month).',
        'formula': "-1 × (monthly value ÷ days in services month). Flat-spread within the services month the FBT work happened.",
        'notes': 'Services-month flat-spread per Jack 2026-07-01.',
    },
    'FBT Routing Non-Compliance': {
        'what': 'Penalty fee when inbound routing requirements aren\'t followed.',
        'source': 'FBT Billing XLSX (per-line $ per services month).',
        'formula': "-1 × (monthly value ÷ days in services month). Flat-spread within the services month the FBT work happened.",
        'notes': 'Services-month flat-spread per Jack 2026-07-01.',
    },
    'FBT Outbound No-Show': {
        'what': 'Penalty fee for missed outbound pickup appointments.',
        'source': 'FBT Billing XLSX (per-line $ per services month).',
        'formula': "-1 × (monthly value ÷ days in services month). Flat-spread within the services month the FBT work happened.",
        'notes': 'Services-month flat-spread per Jack 2026-07-01.',
    },
    'FBT Delayed Response Fee': {
        'what': 'Penalty fee for delayed responses to FBT requests.',
        'source': 'FBT Billing XLSX (per-line $ per services month).',
        'formula': "-1 × (monthly value ÷ days in services month). Flat-spread within the services month the FBT work happened.",
        'notes': 'Services-month flat-spread per Jack 2026-07-01.',
    },
    'FBT Disposal Fee': {
        'what': 'Cost to dispose of obsolete or returned inventory.',
        'source': 'FBT Billing XLSX (per-line $ per services month).',
        'formula': "-1 × (monthly value ÷ days in services month). Flat-spread within the services month the FBT work happened.",
        'notes': 'Services-month flat-spread per Jack 2026-07-01.',
    },
    'FBT Return Shipping (VAS)': {
        'what': 'Value-Added Service fee for return shipping handling.',
        'source': 'FBT Billing XLSX (per-line $ per services month).',
        'formula': "-1 × (monthly value ÷ days in services month). Flat-spread within the services month the FBT work happened.",
        'notes': 'Services-month flat-spread per Jack 2026-07-01.',
    },
    'FBT Return to Seller Handling': {
        'what': 'Fee for handling returns sent back to the seller.',
        'source': 'FBT Billing XLSX (per-line $ per services month).',
        'formula': "-1 × (monthly value ÷ days in services month). Flat-spread within the services month the FBT work happened.",
        'notes': 'Services-month flat-spread per Jack 2026-07-01.',
    },
    'FBT Inbound Return Operation': {
        'what': 'Operation fee for processing inbound returns.',
        'source': 'FBT Billing XLSX (per-line $ per services month).',
        'formula': "-1 × (monthly value ÷ days in services month). Flat-spread within the services month the FBT work happened.",
        'notes': 'Services-month flat-spread per Jack 2026-07-01.',
    },
    'FBT Warehouse Compensation': {
        'what': 'TikTok\'s compensation for FBT warehouse damage to your stock.',
        'source': 'Settlement XLSX → Adjustment rows where Type = "FBT warehouse compensation".',
        'formula': 'sum by Statement date. Positive (a credit back to you).',
        'notes': '',
    },
    'FBT Warehouse Service Fee': {
        'what': 'In-warehouse fees TikTok charges for FBT services (storage, handling).',
        'source': 'Settlement XLSX → Adjustment rows where Type = "FBT warehouse service fee using GMV payments".',
        'formula': 'sum by Statement date. Negative.',
        'notes': 'Distinct from the FBT Storage Fee in FBT Billing — this one comes from settlement adjustments.',
    },

    # ============================ PLATFORM FEES ============================
    'Referral Fee': {
        'what': 'TikTok\'s commission on successful orders.',
        'source': 'Settlement XLSX → Referral fee column on Order rows.',
        'formula': 'sum by Statement date. Negative.',
        'notes': 'TikTok\'s primary monetization — typically 5-10% of order value.',
    },
    'Refund Admin Fee': {
        'what': '20% administrative deduction TikTok keeps from refunded referral fees.',
        'source': 'Settlement XLSX → Refund administration fee column.',
        'formula': 'sum by Statement date. Negative.',
        'notes': 'When an order is refunded, TikTok refunds the referral fee but keeps 20% as an admin fee.',
    },
    'Campaign Service Fee': {
        'what': 'Fee charged for participating in TikTok platform campaigns.',
        'source': 'Settlement XLSX → Campaign service fee column.',
        'formula': 'sum by Statement date.',
        'notes': 'Usually small or $0.',
    },
    'Violation Fee': {
        'what': 'Penalty fee for policy violations.',
        'source': 'Settlement XLSX → Adjustment rows where Type contains "Violation fee".',
        'formula': 'sum by Statement date. Negative.',
        'notes': 'Fires when TikTok deducts for unpleasant buyer experiences due to seller fault.',
    },
    'TikTok Shop Reimb': {
        'what': 'TikTok\'s reimbursement for seller losses due to return/refund rules.',
        'source': 'Settlement XLSX → Adjustment rows where Type = "TikTok Shop reimbursement".',
        'formula': 'sum by Statement date. Positive.',
        'notes': '',
    },
    'Rebate': {
        'what': 'Rebate credits issued by TikTok.',
        'source': 'Settlement XLSX → Adjustment rows where Type = "Rebate".',
        'formula': 'sum by Statement date. Positive.',
        'notes': '',
    },
    'Co-funded Promotion (seller-funded)': {
        'what': 'Seller\'s share of a co-funded promotion with TikTok.',
        'source': 'Settlement XLSX → Co-funded promotion (seller-funded) column on Order rows.',
        'formula': 'sum by Statement date.',
        'notes': 'Your contribution to discounts where TikTok also chipped in.',
    },
    'Co-funded Promotion Campaign Period Fee': {
        'what': 'Recurring fee TikTok charges during Co-funded Promotion campaign windows.',
        'source': 'Settlement XLSX → Co-funded Promotion campaign period fee column on Order rows.',
        'formula': 'sum by Statement date. Negative.',
        'notes': 'Separate from the seller-funded discount portion — this is the campaign participation fee.',
    },
    'Smart Promotion Fee': {
        'what': 'Per-order fee TikTok charges when Smart Promotions is enabled on your account.',
        'source': 'Settlement XLSX → Smart Promotion fee column on Order rows.',
        'formula': 'sum by Statement date. Negative.',
        'notes': 'Opted into Smart Promotions in June 2026. Before that, this column was always $0. New sub-component of TikTok\'s Fees aggregate.',
    },
    'Smart Promotion Campaign Period Fee': {
        'what': 'Recurring fee during Smart Promotion campaign windows.',
        'source': 'Settlement XLSX → Smart Promotion campaign period fee column on Order rows.',
        'formula': 'sum by Statement date. Negative.',
        'notes': 'Structural cousin of Co-funded Promotion Campaign Period Fee. Started firing June 2026 alongside Smart Promotion Fee.',
    },
    'Unclassified Adjustments': {
        'what': 'Catch-all bucket for Settlement adjustment Types we don\'t have explicit mappings for.',
        'source': 'Settlement XLSX → Adjustment rows where Type isn\'t in TYPE_TO_FIELD map.',
        'formula': 'sum by Statement date.',
        'notes': 'If this is non-zero, check ImportLog notes on the History page — it lists the actual Type names that fell here.',
    },

    'GROSS PROFIT': {
        'what': 'Profit before marketing and G&A costs.',
        'source': 'Computed.',
        'formula': 'Net Revenue + COGS + all Fulfillment lines + all Platform Fee lines.',
        'notes': '',
    },

    # ============================ MARKETING ============================
    'Ad Spend — Direct to TikTok (cash)': {
        'what': 'Raw ad spend on TikTok before any credits or discounts.',
        'source': 'Campaign Overview XLSX → Cost column.',
        'formula': 'sum(Cost) per day. Stored negative.',
        'notes': 'This is the gross billable spend, BEFORE TBSM/promo credits offset it.',
    },
    'Less: TBSM Savings': {
        'what': 'Discount savings from agency-loaded credits (TBSM 6%, KDMT 10%, etc.).',
        'source': 'Ad Discounts ledger (FIFO engine).',
        'formula': 'Per-day savings = (amount drawn from agency credit) × (discount rate on that credit).',
        'notes': 'Only flows into the P&L when "Feed P&L" is enabled on the Ad Discounts page. See the Ad Discounts page for daily breakdown.',
    },
    'Less: TT Promo Credits': {
        'what': 'Savings from free TikTok promotional credits drawn against ad spend.',
        'source': 'Ad Discounts ledger.',
        'formula': 'Per-day savings = full amount drawn from free promo layers (since cost is $0).',
        'notes': 'When "Feed P&L" is enabled, comes from the FIFO engine. Falls back to manual Monthly Input flat-spread otherwise.',
    },
    'Total Ad Spend': {
        'what': 'Net ad cost after TBSM Savings and TT Promo Credits.',
        'source': 'Computed.',
        'formula': 'Ad Spend + Less: TBSM Savings + Less: TT Promo Credits.',
        'notes': 'This is your true ad cost.',
    },
    'Platform (Affiliate Commission)': {
        'what': 'Total commission paid to creators across all TikTok affiliate programs.',
        'source': 'Settlement XLSX → sum of 4 columns: Affiliate Commission + Affiliate partner commission + Affiliate Shop Ads commission + Affiliate Partner shop ads commission.',
        'formula': 'Sum of all 4 columns, by Statement date. Negative.',
        'notes': 'Per Lindsay/Jack 2026-06-25 — affiliate commission ties to Statement date (day TikTok finalized the commission payout on its statement).',
    },
    'Off-Platform (1% method)': {
        'what': 'Estimated cost of off-platform creator commissions (1% of GMV method).',
        'source': 'Monthly Input (manual entry).',
        'formula': '-1 × (monthly value ÷ days in month).',
        'notes': 'Manual estimate when creators are paid outside TikTok\'s affiliate system.',
    },
    'Monthly Retainers': {
        'what': 'Fixed monthly creator/influencer retainers.',
        'source': 'Monthly Input.',
        'formula': '-1 × (monthly value ÷ days in month).',
        'notes': '',
    },
    'Outsourced Agency': {
        'what': 'Outsourced creative/agency costs (e.g., Creatify).',
        'source': 'Monthly Input.',
        'formula': '-1 × (monthly value ÷ days in month).',
        'notes': '',
    },
    'TOTAL MARKETING': {
        'what': 'Total marketing cost (ads + creators + agency).',
        'source': 'Computed.',
        'formula': 'Total Ad Spend + Platform (Affiliate) + Off-Platform + Retainers + Outsourced Agency.',
        'notes': '',
    },

    # ============================ G&A ============================
    'Team Spend': {
        'what': 'Team / payroll costs.',
        'source': 'Monthly Input.',
        'formula': '-1 × (monthly value ÷ days in month).',
        'notes': '',
    },
    'Software & Tools': {
        'what': 'Recurring software and tooling costs.',
        'source': 'Monthly Input.',
        'formula': '-1 × (monthly value ÷ days in month).',
        'notes': '',
    },
    'Other G&A': {
        'what': 'Other general & administrative costs.',
        'source': 'Monthly Input.',
        'formula': '-1 × (monthly value ÷ days in month).',
        'notes': '',
    },
    'Chargebacks': {
        'what': 'Credit card chargeback losses.',
        'source': 'Settlement XLSX → Adjustment rows where Type = "Chargeback".',
        'formula': 'sum by Statement date. Negative.',
        'notes': 'Funds reversed by customers\' card issuers due to disputes.',
    },
    'TOTAL G&A': {
        'what': 'Total general & administrative costs.',
        'source': 'Computed.',
        'formula': 'Team Spend + Software & Tools + Other G&A + Chargebacks + Unclassified Adjustments.',
        'notes': '',
    },

    'NET PROFIT': {
        'what': 'Bottom-line profit or loss.',
        'source': 'Computed.',
        'formula': 'Gross Profit + Total Marketing + Total G&A.',
        'notes': 'All marketing and G&A values are negative, so adding them subtracts from Gross Profit.',
    },

    # Less: TT Promo Credits — already covered above. (kept for explicit indexing)
}


def get_doc(label):
    """Return the doc dict for a given line item label, or None if not documented."""
    return LINE_ITEM_DOCS.get(label.strip())
