from django.db import models


class City(models.Model):
    name = models.CharField(max_length=64, unique=True)
    id = models.AutoField(primary_key=True, verbose_name='ID')
    country = models.CharField(max_length=64, default='Country')

    def __str__(self):
        return f'{self.name}({self.country})'

    class Meta:
        verbose_name = 'City'
        verbose_name_plural = 'Cities'
        ordering = ['name', 'country']
