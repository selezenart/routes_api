from django.urls import path

from cities.views import *

urlpatterns = [
    #path('', home, name='home'),
    path('', CityListView.as_view(), name='home'),
    path('details/<int:pk>/', CityDetailView.as_view(), name='details'),
    path('add/', CityCreateView.as_view(), name='create'),
    path('edit/<int:pk>', CityUpdateView.as_view(), name='update'),
    path('delete/<int:pk>/', CityDeleteView.as_view(), name='delete'),


]