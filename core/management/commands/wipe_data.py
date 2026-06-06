"""Wipe imported data tables (keeps COGS + Monthly Inputs). For dev/recovery."""
from django.core.management.base import BaseCommand
from core.models import Order, SettlementRow, AnalyticsDay, AdSpendDay, ImportLog


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--what', default='all',
                            help='all | orders | settlement | analytics | ad_spend | logs')

    def handle(self, *args, **opts):
        what = opts['what']
        if what in ('all', 'orders'):
            n = Order.objects.all().delete()[0]
            self.stdout.write(f"Orders deleted: {n}")
        if what in ('all', 'settlement'):
            n = SettlementRow.objects.all().delete()[0]
            self.stdout.write(f"SettlementRows deleted: {n}")
        if what in ('all', 'analytics'):
            n = AnalyticsDay.objects.all().delete()[0]
            self.stdout.write(f"AnalyticsDays deleted: {n}")
        if what in ('all', 'ad_spend'):
            n = AdSpendDay.objects.all().delete()[0]
            self.stdout.write(f"AdSpendDays deleted: {n}")
        if what in ('all', 'logs'):
            n = ImportLog.objects.all().delete()[0]
            self.stdout.write(f"ImportLogs deleted: {n}")
