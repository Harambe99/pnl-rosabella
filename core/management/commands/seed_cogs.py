"""Seed the COGS table with Christine-approved values + new Glutathione SKUs."""
from django.core.management.base import BaseCommand
from core.models import COGSItem
from decimal import Decimal

SEED = [
    # (sku_id, product_name, sku_variant, cogs, supplier_ref, notes, approval, listing_id)
    ('1730575134849929990', 'Rosabella Organic Beetroot Capsules (1300mg)', 'Default', '2.05', 'ROS-BEET-CAP-1PK', '', 'Y', '1730575102594028294'),
    ('1731256552650281734', '3 Pack of Rosabella Organic Beetroot Capsules', 'Default', '6.20', 'ROS-BEET-CAP-3PK', '', 'Y', '1731256513741558534'),
    ('1731473803194110726', 'Rosabella Electrolytes', 'Lemon Lime', '4.37', 'ROS-ELEC-LML-PWD-1PK', '', 'Y', '1731473708325835526'),
    ('1731473803194176262', 'Rosabella Electrolytes', 'Orange', '4.26', 'ROS-ELEC-ORG-PWD-1PK', '', 'Y', '1731473708325835526'),
    ('1731581983342760710', 'Rosabella Electrolytes 3-Pack', 'Default', '12.74', 'ROS-ELEC-WOL-BUN3', '', 'Updated - Y', '1731581949694677766'),
    ('1731473803194241798', 'Rosabella Electrolytes', 'Watermelon', '3.91', 'ROS-ELEC-WTM-PWD-1PK', '', 'Y', '1731473708325835526'),
    ('1730575140051194630', 'Rosabella Biotin Gummies', 'Default', '3.75', 'ROS-HAIR-GUM-1PK', 'Legacy variant', 'Y', '1730575100230669062'),
    ('1731531874322649862', 'Rosabella Biotin Gummies', 'Hair, Skin and Nails', '3.75', 'ROS-HAIR-GUM-1PK', '', 'Y', '1730575100230669062'),
    ('1731581969523249926', '3-Pack Rosabella Biotin Gummies', 'Default', '11.25', 'ROS-HAIR-GUM-3PK', '', 'Y', '1731581954862781190'),
    ('1731531888820851462', 'Rosabella Natural Healer', "Nature's Healer", '1.85', 'ROS-HEAL-CAP-1PK', '', 'Updated - Y', '1731100446646833926'),
    ('1732307630421611270', 'Liposomal Glutathione Capsules', 'Default (1-pack)', '3.95', 'ROS-LPGL-CAP-1PK', '', 'Y', '1732307596354622214'),
    ('1732409320576160518', 'Liposomal Glutathione Capsules', 'Glutathione Doubles (2-pack)', '7.90', 'ROS-LPGL-CAP-2PK', 'NEW - verify with Jetpack', 'PENDING', '1732307596354622214'),
    ('1732409320576226054', 'Liposomal Glutathione Capsules', 'Glutathione Triples (3-pack)', '11.85', 'ROS-LPGL-CAP-3PK', 'NEW - verify with Jetpack', 'PENDING', '1732307596354622214'),
    ('1732407859575231238', 'Liposomal Glutathione Capsules', 'Glutathione Triples (legacy?)', '11.85', 'ROS-LPGL-CAP-3PK', 'Legacy variant', 'PENDING', '1732307596354622214'),
    ('1732395188357993222', 'Liposomal Glutathione Capsules', 'Glutathione Triple bundle (legacy?)', '11.85', 'ROS-LPGL-CAP-3PK', 'Legacy variant', 'PENDING', '1732307596354622214'),
    ('1731538111523361542', 'Rosabella Best Sellers Bundle BUN4', 'Default', '10.32', 'ROS-MBSH-TTBS-BUN4', '', 'Updated - Y', '1731538109708079878'),
    ('1731531864174072582', 'Rosabella Moringa Cleanse', 'Moringa Cleanse', '2.20', 'ROS-MCLEA-CAP-1PK', '', 'Updated - Y', '1731332047391331078'),
    ('1731256751470580486', 'Moringa + Beetroot Combo Pack', 'Default', '3.97', 'ROS-MORG-BEET-BUN2', 'listing level SKU', 'Updated - Y', '1731256725498794758'),
    ('1729464033034605318', '2 x Rosabella Moringa Capsules', 'Default', '3.79', 'ROS-MORG-CAP-2PK', '', 'Updated - Y', '1729464033034539782'),
    ('1729827466112635654', '3 Pack of Rosabella Moringa Capsules', 'Default', '5.66', 'ROS-MORG-CAP-3PK', '', 'Updated - Y', '1729826796353524486'),
    ('1731659003189105414', 'Rosabella Moringa Gummies', 'Default', '3.25', 'ROS-MORG-GUM-1PK', '', 'Y', '1731658964563825414'),
    ('1731637797094134534', '2-pack Rosabella Moringa and Saffron Blend', 'Default', '4.47', 'ROS-MORG-SAFF-BUN2', '', 'Updated - Y', '1731637795307885318'),
    ('1731647277130945286', 'Rosabella Best Sellers Bundle $9.99 each', 'Default', '8.27', 'ROS-MSH-TTBS-BUN3', '', 'Updated - Y', '1731647538442375942'),
    ('1731531863581954822', 'Rosabella Saffron Supplement', 'Saffron', '2.55', 'ROS-SAFF-CAP-1PK', '', 'Updated - Y', '1731172420560720646'),
    ('1731581918898066182', 'Rosabella 3-Pack Saffron Blend', 'Default', '7.70', 'ROS-SAFF-CAP-3PK', '', 'Updated - Y', '1731581891760132870'),
]


class Command(BaseCommand):
    help = 'Seed initial COGS table'

    def handle(self, *args, **opts):
        # IMPORTANT: only the cogs_per_order field is preserved on existing rows.
        # Editing a COGS value on the page must NOT get overwritten by the next deploy.
        # Metadata (name, variant, supplier_ref, notes, approval, listing_id) is always refreshed.
        created, metadata_refreshed = 0, 0
        for row in SEED:
            sku_id, name, variant, cogs, sref, notes, app, listing = row
            obj, was_created = COGSItem.objects.get_or_create(
                sku_id=sku_id,
                defaults={
                    'product_name': name,
                    'sku_variant': variant,
                    'cogs_per_order': Decimal(cogs),
                    'supplier_ref': sref,
                    'notes': notes,
                    'approval': app,
                    'listing_id': listing,
                }
            )
            if was_created:
                created += 1
            else:
                # Refresh metadata only — preserve any user-edited cogs_per_order
                obj.product_name = name
                obj.sku_variant = variant
                obj.supplier_ref = sref
                obj.notes = notes
                obj.approval = app
                obj.listing_id = listing
                obj.save(update_fields=['product_name', 'sku_variant', 'supplier_ref',
                                        'notes', 'approval', 'listing_id'])
                metadata_refreshed += 1
        self.stdout.write(self.style.SUCCESS(
            f'COGS seed: {created} created, {metadata_refreshed} metadata-refreshed '
            f'(cogs_per_order preserved on existing rows).'))
