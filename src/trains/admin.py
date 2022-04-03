from django.contrib import admin

from trains.models import Train


class TrainAdmin(admin.ModelAdmin):
    """
        Admin View for Train
    """
    list_display = ('name', 'departs_from', 'arrives_to', 'travel_time')
    list_editable = ('travel_time',)


admin.site.register(Train, TrainAdmin)
