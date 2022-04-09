"""travel URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include

from routes.views import RouteFindView, RouteCreateView, send_form, RouteListView, RouteDetailView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RouteFindView.as_view(), name='home'),
    path('save_route/', RouteCreateView.as_view(), name='save_route'),
    path('create_route/', send_form, name='send_form'),
    #path('about/', about),
    path('cities/', include(('cities.urls', 'cities'))),
    path('trains/', include(('trains.urls', 'trains'))),
    path('list/', RouteListView.as_view(), name='list'),
    path('details/<int:pk>/', RouteDetailView.as_view(), name='details'),
]
