# Generated by Django 5.2 on 2025-04-09 23:48

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tg', '0009_tguser_referral_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='shop',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='tg.shop'),
        ),
    ]
