from django.urls import path

from cities.views import *

urlpatterns = [
    path('', home, name='home'),
    path('details/<int:pk>/', CityDetailView.as_view(), name='details')

]