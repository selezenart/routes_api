from django import forms

from cities.models import City


class CityForm(forms.ModelForm):
    name = forms.CharField(label='City',
                           widget=forms.TextInput(attrs={
                               'class': 'form-control',
                               'placeholder': 'Input city name'}))
    country = forms.CharField(label='Country',
                              widget=forms.TextInput(attrs={
                                  'class': 'form-control',
                                  'placeholder': 'Input country name'}))

    class Meta:
        model = City
        fields = ('name', 'country')

