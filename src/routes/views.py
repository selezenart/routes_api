from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import FormView, DetailView, CreateView, ListView

from cities.models import City
from routes.forms import RouteForm, RouteModelForm
from routes.models import Route
from routes.utils import get_routes
from trains.models import Train


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


def send_form(request):
    if request.method == 'POST':
        context = {}
        data = request.POST
        if data:
            total_time = int(data['total_time'])
            startpoint_id = int(data['startpoint'])
            endpoint_id = int(data['endpoint'])
            trains_id = data['trains'].split(',')
            trains_list = [int(t) for t in trains_id if t.isdigit()]
            trains_qs = Train.objects.filter(id__in=trains_list).select_related('departs_from', 'arrives_to')
            cities_qs = City.objects.filter(id__in=[startpoint_id, endpoint_id]).in_bulk()
            form = RouteModelForm(
                initial={
                    'startpoint': cities_qs[startpoint_id],
                    'endpoint': cities_qs[endpoint_id],
                    'travel_duration': total_time,
                    'trains': trains_qs
                }
            )
            context['form'] = form
        return render(request, "routes/create.html", context)
    else:
        messages.error(request, "Unable to create route without choosing it from list.")
        return redirect('/')


class RouteCreateView(CreateView):
    model = Route
    template_name = "routes/create.html"
    form_class = RouteModelForm
    success_url = reverse_lazy('home')
    success_message = "Route was successfully created!"

    def post(self, request, *args, **kwargs):
        form = self.form_class(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, self.success_message)
            return redirect('/')
        return render(request, "routes/create.html", {{'form': form}})


class RouteListView(ListView):
    model = Route
    template_name = "routes/list.html"
    paginate_by = 10


class RouteDetailView(DetailView):
    queryset = Route.objects.all()
    model = Route
    template_name = "routes/details.html"
