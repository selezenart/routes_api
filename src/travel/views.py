from django.http import HttpResponse
from django.shortcuts import render


def home(request):
    return render(request, 'home.html', {'name': "User"})


def about(request):
    return render(request, 'about.html')
