# Generated by Django 3.1.3 on 2022-03-24 23:30

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cities', '0003_auto_20220324_2324'),
    ]

    operations = [
        migrations.AlterField(
            model_name='city',
            name='country',
            field=models.CharField(default='Country', max_length=64),
        ),
        migrations.AlterField(
            model_name='city',
            name='id',
            field=models.AutoField(primary_key=True, serialize=False, verbose_name='ID'),
        ),
    ]
