from django.core.exceptions import ValidationError
from django.db import models


class Route(models.Model):
    id = models.AutoField(primary_key=True, verbose_name='ID')
    name = models.CharField(max_length=64, unique=True, verbose_name="Route's name")
    travel_duration = models.PositiveSmallIntegerField(verbose_name='Trip duration')
    startpoint = models.ForeignKey('cities.City', on_delete=models.CASCADE, related_name='trip_startpoint_set',
                                   verbose_name='Trip starts from:')
    endpoint = models.ForeignKey('cities.City', on_delete=models.CASCADE, related_name='trip_endpoint_set',
                                 verbose_name='Trip ends at:')
    trains = models.ManyToManyField('trains.Train', verbose_name="List of trains")

    class Meta:
        verbose_name = "Route"
        verbose_name_plural = "Routes"
        ordering = ['startpoint', 'endpoint', 'name', ]

   # def clean(self):
   #     trains_time = self.trains.values_list('travel_time', flat=True)
   #     if trains_time < self.travel_duration:
   #         self.delete()
   #         raise ValidationError(
   #             f'You cannot spend less time in trip than in included trains. Selected trains take {trains_time} hours '
   #             f'and the whole route takes {self.travel_duration} hours')
#
   # def save(self, *args, **kwargs):
   #     super(Route, self).save(*args, **kwargs)
   #     self.clean()

    def __str__(self):
        return f'Route №{self.name} from {self.startpoint} to {self.endpoint}'
