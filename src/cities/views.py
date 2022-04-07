from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.generic import DetailView, CreateView, UpdateView, DeleteView, ListView

from cities.forms import CityForm
from cities.models import City

__all__ = (
    'CityDetailView', 'CityCreateView', 'CityUpdateView', 'CityDeleteView', 'CityListView',
)


class CityDetailView(DetailView):
    queryset = City.objects.all()
    template_name = "cities/details.html"


class CityCreateView(SuccessMessageMixin, CreateView):
    model = City
    form_class = CityForm
    template_name = "cities/create.html"
    success_url = reverse_lazy('cities:home')
    success_message = "City was successfully added!"


class CityUpdateView(SuccessMessageMixin, UpdateView):
    model = City
    form_class = CityForm
    template_name = "cities/update.html"
    success_url = reverse_lazy('cities:home')
    success_message = "City was successfully edited!"


class CityDeleteView(SuccessMessageMixin, DeleteView):
    model = City
    template_name = "cities/delete.html"
    success_url = reverse_lazy('cities:home')
    success_message = "City was successfully deleted!"

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, self.success_message)
        return super(CityDeleteView, self).delete(request, *args, **kwargs)


class CityListView(ListView):
    model = City
    paginate_by = 5
    template_name = "cities/home.html"
