# Generated by Django 5.2 on 2025-04-09 22:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tg', '0007_withdrawalmode_ltc_amount_withdrawalmode_requisite'),
    ]

    operations = [
        migrations.AddField(
            model_name='withdrawalmode',
            name='finish',
            field=models.BooleanField(default=False),
        ),
    ]
