from django import forms

from cities.models import City
from trains.models import Train
from routes.models import Route


class RouteForm(forms.Form):
    departs_from = forms.ModelChoiceField(label='Departure', queryset=City.objects.all(), widget=forms.Select(attrs={
        'class': 'form-control single_choice'}))
    arrives_to = forms.ModelChoiceField(label='Arrival', queryset=City.objects.all(), widget=forms.Select(attrs={
        'class': 'form-control single_choice'}))
    cities = forms.ModelMultipleChoiceField(
        label='Cities to visit', queryset=City.objects.all(), required=False, widget=forms.SelectMultiple(
            attrs={'class': 'form-control multiple_choice'}))
    travel_duration = forms.IntegerField(label="Duration", widget=forms.NumberInput(attrs={
        'class': 'form-control',
        'placeholder': 'Input travel duration',
    }))


class RouteModelForm(forms.ModelForm):
    name = forms.CharField(label='Route name', widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': 'Input route name'}))
    startpoint = forms.ModelChoiceField(queryset=City.objects.all(), widget=forms.HiddenInput())
    endpoint = forms.ModelChoiceField(queryset=City.objects.all(), widget=forms.HiddenInput())
    travel_duration = forms.IntegerField(widget=forms.HiddenInput())
    trains = forms.ModelMultipleChoiceField(
        queryset=Train.objects.all(), required=True, widget=forms.SelectMultiple(
            attrs={'class': 'form-control d-none'}))

    class Meta:
        model = Route
        fields = '__all__'
