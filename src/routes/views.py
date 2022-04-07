from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import FormView, DetailView

from routes.forms import RouteForm
from routes.models import Route
from routes.utils import get_routes


class RouteFindView(FormView):
    model = Route
    form_class = RouteForm
    template_name = "routes/home.html"
    success_url = reverse_lazy('home')

    def get(self, request, *args, **kwargs):
        form = self.form_class()
        return render(request, self.template_name, {'form': form})

    def post(self, request, *args, **kwargs):
        form = self.form_class(request.POST)
        if form.is_valid():
            try:
                context = get_routes(request, form)
            except ValueError as e:
                messages.error(request, e)
                return render(request, self.template_name, {'form': form})
            return render(request, "routes/search_result.html", context)

