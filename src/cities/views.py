from django.shortcuts import render, get_object_or_404
from django.views.generic import DetailView

from cities.models import City

__all__ = (
    'home', 'CityDetailView',
)


def home(request):
    qs = City.objects.all()
    context = {'objects_list': qs}
    return render(request, 'cities/home.html', context)
 

class CityDetailView(DetailView):
    queryset = City.objects.all()
    template_name = "cities/details.html"
    
