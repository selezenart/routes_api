from django.core.exceptions import ValidationError
from django.db import models


class Train(models.Model):
    id = models.AutoField(primary_key=True, verbose_name='ID')
    name = models.CharField(max_length=64, unique=True, verbose_name='Train number')
    travel_time = models.PositiveSmallIntegerField(verbose_name='Duration')
    departs_from = models.ForeignKey('cities.City', on_delete=models.CASCADE, related_name='departs_from_set',
                                     verbose_name='Departs from:')
    arrives_to = models.ForeignKey('cities.City', on_delete=models.CASCADE, related_name='arrives_to_set',
                                   verbose_name='Arrives to:')

    class Meta:
        verbose_name = "Train"
        verbose_name_plural = "Trains"
        ordering = ['departs_from', 'arrives_to', 'name',]

    def clean(self):
        if self.departs_from == self.arrives_to:
            raise ValidationError('Train cannot arrive and depart to same city')

    def save(self, *args, **kwargs):
        self.clean()
        super(Train, self).save(*args, **kwargs)

    def __str__(self):
        return f'Train №{self.name} from {self.departs_from} to {self.arrives_to}'
