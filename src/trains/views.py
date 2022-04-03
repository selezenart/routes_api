from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.generic import DetailView, CreateView, UpdateView, DeleteView, ListView

from trains.forms import TrainForm
from trains.models import Train

__all__ = (
    'TrainCreateView', 'TrainUpdateView', 'TrainDeleteView',
    'TrainListView', 'TrainDetailView',
)


class TrainDetailView(DetailView):
    queryset = Train.objects.all()
    template_name = "trains/details.html"


class TrainCreateView(SuccessMessageMixin, CreateView):
    model = Train
    form_class = TrainForm
    template_name = "trains/create.html"
    success_url = reverse_lazy('trains:home')
    success_message = "Train was successfully added!"


class TrainUpdateView(SuccessMessageMixin, UpdateView):
    model = Train
    form_class = TrainForm
    template_name = "trains/update.html"
    success_url = reverse_lazy('trains:home')
    success_message = "Train was successfully edited!"


class TrainDeleteView(SuccessMessageMixin, DeleteView):
    model = Train
    template_name = "trains/delete.html"
    success_url = reverse_lazy('trains:home')
    success_message = "Train was successfully deleted!"

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, self.success_message)
        return super(TrainDeleteView, self).delete(request, *args, **kwargs)


class TrainListView(ListView):
    model = Train
    paginate_by = 5
    template_name = "trains/home.html"
