from django.db import models
from django.urls import reverse


class City(models.Model):
    name = models.CharField(max_length=64)
    id = models.AutoField(primary_key=True, verbose_name='ID')
    country = models.CharField(max_length=64)

    def __str__(self):
        return f'{self.name}({self.country})'

    class Meta:
        verbose_name = 'City'
        verbose_name_plural = 'Cities'
        ordering = ['name', 'country']
        unique_together = ('name', 'country')

    def get_absolute_url(self):
        return reverse('cities:details', kwargs={'pk': self.id})
