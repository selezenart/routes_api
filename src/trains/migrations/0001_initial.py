# Generated by Django 3.1.3 on 2022-04-03 13:23

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('cities', '0006_auto_20220327_1638'),
    ]

    operations = [
        migrations.CreateModel(
            name='Train',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=64, unique=True, verbose_name='Train number')),
                ('travel_time', models.PositiveSmallIntegerField(verbose_name='Duration')),
                ('arrives_to', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='arrives_to_set', to='cities.city', verbose_name='Arrives to:')),
                ('departs_from', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='departs_from_set', to='cities.city', verbose_name='Departs from:')),
            ],
            options={
                'verbose_name': 'Train',
                'verbose_name_plural': 'Trains',
                'ordering': ['departs_from', 'arrives_to', 'name'],
            },
        ),
    ]
