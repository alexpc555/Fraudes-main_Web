"""Configuración, eventos y adaptadores desacoplados de notificaciones CU-21."""

from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .configuracion_services import verificar_autorizacion_configuracion
from .models import (
    ConfiguracionAplicacion,
    ConfiguracionNotificaciones,
    EventoNotificacion,
    EstadoLlamada,
)


@dataclass
class ResultadoEnvio:
    estado: str
    detalle: str = ''


class AdaptadorPushAndroid:
    """Punto de extensión para FCM; queda pendiente mientras no haya integración."""

    def enviar(self, evento):
        return ResultadoEnvio(
            EventoNotificacion.Estado.PENDIENTE,
            'FCM no está configurado; el evento quedó registrado para integración Android.',
        )


class AdaptadorCorreoElectronico:
    def enviar(self, evento):
        if not getattr(settings, 'NOTIFICACIONES_EMAIL_ACTIVAS', False) or not evento.destinatario_correo:
            return ResultadoEnvio(
                EventoNotificacion.Estado.PENDIENTE,
                'El correo no está habilitado o el contacto no tiene dirección registrada.',
            )
        enviados = send_mail(
            subject=f'Alerta telefónica {evento.nivel_riesgo.lower()} · {evento.llamada.identificador}',
            message=evento.mensaje,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
            recipient_list=[evento.destinatario_correo],
            fail_silently=False,
        )
        if enviados:
            return ResultadoEnvio(EventoNotificacion.Estado.ENVIADA, 'Correo enviado.')
        return ResultadoEnvio(EventoNotificacion.Estado.ERROR, 'El servidor de correo no aceptó el mensaje.')


class AdaptadorOtroCanal:
    def enviar(self, evento):
        return ResultadoEnvio(EventoNotificacion.Estado.PENDIENTE, 'El canal todavía no está conectado.')


ADAPTADORES = {
    EventoNotificacion.Canal.ANDROID_PUSH: AdaptadorPushAndroid,
    EventoNotificacion.Canal.CORREO: AdaptadorCorreoElectronico,
    EventoNotificacion.Canal.OTRO: AdaptadorOtroCanal,
}


def obtener_contactos_notificacion(familiar, adulto_mayor):
    """Regresa contactos activos de CU-19, nunca una agenda alternativa."""
    if not verificar_autorizacion_configuracion(familiar, adulto_mayor):
        raise PermissionDenied('No tienes autorización para consultar estos contactos.')
    from .models import ContactoConfianza
    return ContactoConfianza.objects.filter(
        usuario_protegido=adulto_mayor,
        activo=True,
    ).order_by('nombre')


def obtener_configuracion_notificaciones(familiar, adulto_mayor):
    if not verificar_autorizacion_configuracion(familiar, adulto_mayor):
        raise PermissionDenied('No tienes autorización para consultar esta configuración.')
    return ConfiguracionNotificaciones.objects.select_related('contacto_confianza').filter(
        adulto_mayor=adulto_mayor,
        activo=True,
        contacto_confianza__activo=True,
        contacto_confianza__usuario_protegido=adulto_mayor,
    ).first()


def obtener_configuracion_notificaciones_sin_cuenta(adulto_mayor):
    """Consulta las alertas elegidas desde el perfil local del Adulto mayor."""
    return ConfiguracionNotificaciones.objects.select_related('contacto_confianza').filter(
        adulto_mayor=adulto_mayor,
        activo=True,
        contacto_confianza__activo=True,
        contacto_confianza__usuario_protegido=adulto_mayor,
    ).first()


@transaction.atomic
def guardar_contacto_notificacion_sin_cuenta(adulto_mayor, contacto_id, confirmar=False):
    """Permite al Adulto mayor seleccionar un contacto sin crear cuenta Familiar."""
    from .models import ContactoConfianza

    if not confirmar:
        raise ValidationError('Confirma que el contacto es correcto antes de guardar.')
    contacto = ContactoConfianza.objects.filter(
        pk=contacto_id,
        usuario_protegido=adulto_mayor,
        activo=True,
    ).first()
    if contacto is None:
        raise ValidationError('El contacto no existe o está inactivo. Agrégalo primero a Números seguros.')

    configuracion, _ = ConfiguracionNotificaciones.objects.get_or_create(adulto_mayor=adulto_mayor)
    configuracion.familiar_responsable = None
    configuracion.contacto_confianza = contacto
    configuracion.activo = True
    configuracion.save()

    configuracion_app, _ = ConfiguracionAplicacion.objects.get_or_create(adulto_mayor=adulto_mayor)
    configuracion_app.notificaciones_habilitadas = True
    configuracion_app.actualizado_por = adulto_mayor
    configuracion_app.completado_por = None
    configuracion_app.completado_en = None
    configuracion_app.save(update_fields=[
        'notificaciones_habilitadas', 'actualizado_por', 'completado_por',
        'completado_en', 'actualizado_en',
    ])
    return configuracion


@transaction.atomic
def guardar_contacto_notificacion(familiar, adulto_mayor, contacto_id, confirmar=False):
    if not verificar_autorizacion_configuracion(familiar, adulto_mayor):
        raise PermissionDenied('No tienes autorización para modificar esta configuración.')
    if not confirmar:
        raise ValidationError('Confirma el contacto antes de guardar la configuración.')
    from .models import ContactoConfianza
    contacto = ContactoConfianza.objects.filter(
        pk=contacto_id,
        usuario_protegido=adulto_mayor,
        activo=True,
    ).first()
    if contacto is None:
        raise ValidationError('El contacto seleccionado no existe o está inactivo.')

    configuracion, _ = ConfiguracionNotificaciones.objects.get_or_create(adulto_mayor=adulto_mayor)
    configuracion.familiar_responsable = familiar
    configuracion.contacto_confianza = contacto
    configuracion.activo = True
    configuracion.save()

    # CU-20 mantiene la preferencia general; la selección de contacto completa CU-21.
    config_app, _ = ConfiguracionAplicacion.objects.get_or_create(
        adulto_mayor=adulto_mayor,
        defaults={'actualizado_por': familiar},
    )
    config_app.notificaciones_habilitadas = True
    config_app.actualizado_por = familiar
    config_app.completado_por = None
    config_app.completado_en = None
    config_app.save(update_fields=[
        'notificaciones_habilitadas', 'actualizado_por', 'completado_por',
        'completado_en', 'actualizado_en',
    ])
    return configuracion


def _mensaje_seguro(llamada, nivel, tipo, clasificacion):
    ahora = timezone.localtime()
    if tipo == EventoNotificacion.Tipo.LLAMADA_ACEPTADA:
        motivo = 'El Adulto mayor aceptó una llamada que conserva señales de riesgo. Verifiquen su identidad por un canal oficial.'
    elif nivel == 'ROJO':
        motivo = 'Se detectó una llamada de riesgo alto. Recomienda no compartir datos ni hacer pagos y verificar por un canal oficial.'
    else:
        motivo = 'La llamada presentó señales que requieren revisión. Verifiquen la identidad por un canal oficial.'
    numero = llamada.numero_telefonico if llamada.numero_telefonico else 'No disponible'
    return (
        f'Aviso del Asistente Antifraude\n'
        f'Llamada: {llamada.identificador}\n'
        f'Número de origen: {numero}\n'
        f'Nivel: {nivel}\n'
        f'Motivo: {motivo}\n'
        f'Fecha y hora: {ahora.strftime("%d/%m/%Y %H:%M %Z")}'
    )


def generar_evento_notificacion(llamada, tipo=None, clasificacion=None, adaptadores=None):
    """Registra y despacha, sin duplicar la combinación llamada/tipo/canal."""
    if llamada is None or not llamada.usuario_protegido_id:
        return []
    if clasificacion is None:
        clasificacion = llamada.clasificaciones_riesgo.filter(es_actual=True).first()
    if clasificacion is None:
        return []
    nivel = clasificacion.nivel
    if tipo is None:
        if nivel == 'ROJO':
            tipo = EventoNotificacion.Tipo.RIESGO_ALTO
        elif llamada.estado == EstadoLlamada.PERMITIDA and nivel in {'AMARILLO', 'ROJO'}:
            tipo = EventoNotificacion.Tipo.LLAMADA_ACEPTADA
        else:
            return []
    if tipo == EventoNotificacion.Tipo.RIESGO_ALTO and nivel != 'ROJO':
        return []
    if tipo == EventoNotificacion.Tipo.LLAMADA_ACEPTADA and (llamada.estado != EstadoLlamada.PERMITIDA or nivel not in {'AMARILLO', 'ROJO'}):
        return []

    configuracion = ConfiguracionNotificaciones.objects.select_related('contacto_confianza').filter(
        adulto_mayor_id=llamada.usuario_protegido_id,
        activo=True,
        contacto_confianza__activo=True,
        contacto_confianza__usuario_protegido_id=llamada.usuario_protegido_id,
    ).first()
    if configuracion is None:
        return []
    contacto = configuracion.contacto_confianza
    canales = [EventoNotificacion.Canal.ANDROID_PUSH]
    if contacto.correo_electronico:
        canales.append(EventoNotificacion.Canal.CORREO)
    eventos = []
    for canal in canales:
        evento, creado = EventoNotificacion.objects.get_or_create(
            llamada=llamada,
            tipo=tipo,
            canal=canal,
            defaults={
                'configuracion': configuracion,
                'contacto_confianza': contacto,
                'destinatario_nombre': contacto.nombre,
                'destinatario_telefono': contacto.numero_telefonico,
                'destinatario_correo': contacto.correo_electronico,
                'numero_origen': llamada.numero_telefonico or '',
                'nivel_riesgo': nivel,
                'mensaje': _mensaje_seguro(llamada, nivel, tipo, clasificacion),
            },
        )
        eventos.append(evento)
        if creado:
            enviar_notificacion(evento, adaptadores=adaptadores)
    return eventos


def enviar_notificacion(evento, adaptadores=None):
    """Envía mediante adaptador y guarda el resultado real, nunca presupone éxito."""
    adaptadores = adaptadores or ADAPTADORES
    adaptador = adaptadores.get(evento.canal)
    if adaptador is None:
        adaptador = AdaptadorOtroCanal
    if isinstance(adaptador, type):
        adaptador = adaptador()
    ahora = timezone.now()
    try:
        resultado = adaptador.enviar(evento)
        estado = resultado.estado
        if estado not in {choice for choice, _ in EventoNotificacion.Estado.choices}:
            raise ValueError('El adaptador devolvió un estado desconocido.')
        evento.estado = estado
        evento.detalle_envio = resultado.detalle[:1000]
        evento.error_detalle = resultado.detalle[:1000] if estado == EventoNotificacion.Estado.ERROR else ''
        evento.fecha_ultimo_intento = ahora
        evento.fecha_envio = ahora if estado == EventoNotificacion.Estado.ENVIADA else None
    except Exception as exc:  # El error queda registrado sin interrumpir la clasificación de la llamada.
        evento.estado = EventoNotificacion.Estado.ERROR
        evento.error_detalle = str(exc)[:1000]
        evento.detalle_envio = 'Falló el adaptador de notificaciones.'
        evento.fecha_ultimo_intento = ahora
        evento.fecha_envio = None
    evento.save(update_fields=[
        'estado', 'detalle_envio', 'error_detalle', 'fecha_ultimo_intento', 'fecha_envio',
    ])
    return evento
