# Generated by Django 5.2 on 2025-04-09 15:59

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tg', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='tguser',
            name='last_active',
            field=models.DateTimeField(blank=True, default=django.utils.timezone.now, null=True),
        ),
    ]
