from django import forms

from cities.models import City
from trains.models import Train


class TrainForm(forms.ModelForm):
    name = forms.CharField(label="Train", widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': 'Input train number'
    }))
    travel_time = forms.IntegerField(label="Duration", widget=forms.NumberInput(attrs={
        'class': 'form-control',
        'placeholder': 'Input travel duration',
    }))
    departs_from = forms.ModelChoiceField(label='Departure', queryset=City.objects.all(), widget=forms.Select(attrs={
        'class': 'form-control'}))
    arrives_to = forms.ModelChoiceField(label='Arrival', queryset=City.objects.all(), widget=forms.Select(attrs={
        'class': 'form-control'}))

    class Meta:
        model = Train
        fields = '__all__'
