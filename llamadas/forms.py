import re

from django import forms

from .models import ContactoConfianza, NumeroReportado, normalizar_numero_telefonico


class RegistrarLlamadaForm(forms.Form):
    numero_telefonico = forms.CharField(
        label='Número telefónico',
        max_length=16,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. 5522334455'}),
    )

    def clean_numero_telefonico(self):
        numero = (self.cleaned_data['numero_telefonico'] or '').strip()
        if not re.fullmatch(r'^\+?[0-9]{10,15}$', numero):
            raise forms.ValidationError('Ingrese un número telefónico válido.')
        return numero


class ContactoConfianzaForm(forms.ModelForm):
    class Meta:
        model = ContactoConfianza
        fields = ['nombre', 'numero_telefonico', 'correo_electronico', 'relacion', 'descripcion', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'w-full min-h-12 rounded-xl border border-slate-300 p-3 text-base', 'placeholder': 'Ej. María López'}),
            'numero_telefonico': forms.TextInput(attrs={'class': 'w-full min-h-12 rounded-xl border border-slate-300 p-3 text-base', 'placeholder': 'Ej. +52 55 1234 5678'}),
            'correo_electronico': forms.EmailInput(attrs={'class': 'w-full min-h-12 rounded-xl border border-slate-300 p-3 text-base', 'placeholder': 'Opcional; para recibir avisos por correo'}),
            'relacion': forms.TextInput(attrs={'class': 'w-full min-h-12 rounded-xl border border-slate-300 p-3 text-base', 'placeholder': 'Ej. Hija, hermano, cuidador'}),
            'descripcion': forms.Textarea(attrs={'class': 'w-full rounded-xl border border-slate-300 p-3 text-base', 'rows': 3, 'placeholder': 'Describe la relación del contacto'}),
            'activo': forms.CheckboxInput(attrs={'class': 'h-6 w-6 rounded border-slate-300'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        numero = (cleaned_data.get('numero_telefonico') or '').strip()
        usuario = getattr(self, 'usuario_protegido', None)
        if not numero:
            return cleaned_data
        if usuario is None and hasattr(self.instance, 'usuario_protegido') and self.instance.usuario_protegido_id:
            usuario = self.instance.usuario_protegido
        if usuario is not None:
            numero_normalizado = normalizar_numero_telefonico(numero)
            contactos = ContactoConfianza.objects.filter(usuario_protegido=usuario).exclude(pk=self.instance.pk if self.instance else None)
            for contacto in contactos:
                if normalizar_numero_telefonico(contacto.numero_telefonico) == numero_normalizado:
                    raise forms.ValidationError({'numero_telefonico': 'Este contacto ya está registrado para este usuario protegido.'})
        return cleaned_data


class FamiliarSinCuentaForm(ContactoConfianzaForm):
    """Reutiliza la agenda CU-19 sin exponer controles de activación al adulto mayor."""

    class Meta(ContactoConfianzaForm.Meta):
        fields = ['nombre', 'numero_telefonico', 'correo_electronico', 'relacion', 'descripcion']


class NumeroReportadoForm(forms.ModelForm):
    class Meta:
        model = NumeroReportado
        fields = [
            'numero_telefonico', 'identidad_reportada', 'tipo_incidente',
            'cantidad_reportes', 'estado', 'descripcion',
        ]
        labels = {
            'numero_telefonico': 'Número telefónico',
            'identidad_reportada': 'Identidad reportada',
            'tipo_incidente': 'Tipo de incidente',
            'cantidad_reportes': 'Cantidad de reportes',
            'estado': 'Estado del reporte',
            'descripcion': 'Descripción',
        }
        widgets = {
            'numero_telefonico': forms.TextInput(attrs={'class': 'w-full min-h-12 rounded-xl border border-slate-300 p-3 text-base', 'placeholder': 'Ej. 55 1234 5678'}),
            'identidad_reportada': forms.TextInput(attrs={'class': 'w-full min-h-12 rounded-xl border border-slate-300 p-3 text-base', 'placeholder': 'Nombre o identidad conocida, si se conoce'}),
            'tipo_incidente': forms.TextInput(attrs={'class': 'w-full min-h-12 rounded-xl border border-slate-300 p-3 text-base', 'placeholder': 'Ej. intento de fraude'}),
            'cantidad_reportes': forms.NumberInput(attrs={'class': 'w-full min-h-12 rounded-xl border border-slate-300 p-3 text-base', 'min': 1}),
            'estado': forms.Select(attrs={'class': 'w-full min-h-12 rounded-xl border border-slate-300 p-3 text-base'}),
            'descripcion': forms.Textarea(attrs={'class': 'w-full rounded-xl border border-slate-300 p-3 text-base', 'rows': 4, 'placeholder': 'Describe brevemente el reporte'}),
        }

    def clean_numero_telefonico(self):
        numero = (self.cleaned_data.get('numero_telefonico') or '').strip()
        normalizado = normalizar_numero_telefonico(numero)
        for registro in NumeroReportado.objects.exclude(pk=self.instance.pk if self.instance else None):
            if normalizar_numero_telefonico(registro.numero_telefonico) == normalizado:
                raise forms.ValidationError('Este número ya está reportado. Abre el registro existente para editarlo.')
        return numero


class AudioLlamadaForm(forms.Form):
    audio = forms.FileField(
        label='Archivo de audio',
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.wav,.mp3,.m4a,.ogg,.webm'}),
    )
    pregunta_asociada = forms.CharField(
        label='Pregunta asociada',
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. ¿Qué dijo el llamante?'}),
    )
    orden = forms.IntegerField(
        label='Orden de intervención',
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )

    def clean_audio(self):
        audio = self.cleaned_data.get('audio')
        if audio is None:
            raise forms.ValidationError('Debe seleccionar un archivo de audio.')
        nombre = getattr(audio, 'name', '').lower()
        extensiones_permitidas = ['.wav', '.mp3', '.m4a', '.ogg', '.webm']
        if not any(nombre.endswith(ext) for ext in extensiones_permitidas):
            raise forms.ValidationError('Formato de audio no compatible. Use WAV, MP3, M4A, OGG o WEBM.')
        if audio.size <= 0:
            raise forms.ValidationError('El archivo de audio está vacío.')
        return audio
