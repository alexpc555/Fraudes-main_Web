"""Servicios de autorización y estado del asistente inicial CU-20."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    ConfiguracionAplicacion,
    ConfiguracionNotificaciones,
    ContactoConfianza,
    EstadoPermiso,
    RelacionFamiliarAdultoMayor,
)


PERMISOS_REQUERIDOS = (
    ('notificaciones', 'Notificaciones', True),
    ('identificacion_llamadas', 'Identificación y administración de llamadas', True),
    ('contactos_dispositivo', 'Acceso a contactos del dispositivo', False),
)

ESTADO_COMPLETA = 'COMPLETA'
ESTADO_INCOMPLETA = 'INCOMPLETA'
ESTADO_REQUIERE_ATENCION = 'REQUIERE_ATENCION'


def verificar_autorizacion_configuracion(familiar, adulto_mayor):
    """Comprueba la relación autorizada en la base; nunca confía en la interfaz."""
    if not getattr(familiar, 'is_authenticated', False) or not adulto_mayor:
        return False
    return RelacionFamiliarAdultoMayor.objects.filter(
        familiar=familiar,
        adulto_mayor=adulto_mayor,
        autorizado=True,
    ).exists()


def _exigir_autorizacion(familiar, adulto_mayor):
    if not verificar_autorizacion_configuracion(familiar, adulto_mayor):
        raise PermissionDenied('No tienes autorización para configurar este dispositivo.')


@transaction.atomic
def obtener_o_crear_configuracion(familiar, adulto_mayor):
    _exigir_autorizacion(familiar, adulto_mayor)
    configuracion, _ = ConfiguracionAplicacion.objects.get_or_create(adulto_mayor=adulto_mayor)
    for codigo, nombre, esencial in PERMISOS_REQUERIDOS:
        EstadoPermiso.objects.get_or_create(
            configuracion=configuracion,
            codigo=codigo,
            defaults={'nombre': nombre, 'esencial': esencial},
        )
    return configuracion


def _evaluar_estado(configuracion):
    permisos = list(configuracion.permisos.all())
    permisos_por_codigo = {permiso.codigo: permiso for permiso in permisos}
    faltantes = []
    atencion = []
    for codigo, nombre, esencial in PERMISOS_REQUERIDOS:
        permiso = permisos_por_codigo.get(codigo)
        if permiso is None:
            faltantes.append(f'Falta registrar el permiso: {nombre}.')
        elif esencial and permiso.estado != EstadoPermiso.Estado.CONCEDIDO:
            texto = f'{nombre}: {permiso.get_estado_display().lower()}.'
            (atencion if permiso.estado in {EstadoPermiso.Estado.DENEGADO, EstadoPermiso.Estado.NO_DISPONIBLE} else faltantes).append(texto)

    contactos_activos = ContactoConfianza.objects.filter(
        usuario_protegido=configuracion.adulto_mayor,
        activo=True,
    ).count()
    if contactos_activos == 0:
        faltantes.append('Agrega al menos un contacto de confianza activo.')
    config_notificaciones = ConfiguracionNotificaciones.objects.filter(
        adulto_mayor=configuracion.adulto_mayor,
        activo=True,
        contacto_confianza__activo=True,
        contacto_confianza__usuario_protegido=configuracion.adulto_mayor,
    ).exists()
    if not configuracion.notificaciones_habilitadas or not config_notificaciones:
        faltantes.append('Activa las notificaciones de protección.')

    if atencion:
        estado = ESTADO_REQUIERE_ATENCION
    elif faltantes:
        estado = ESTADO_INCOMPLETA
    else:
        estado = ESTADO_COMPLETA
    return {
        'estado': estado,
        'completa': estado == ESTADO_COMPLETA,
        'faltantes': faltantes,
        'requiere_atencion': atencion,
        'contactos_activos': contactos_activos,
        'notificaciones_validas': configuracion.notificaciones_habilitadas and config_notificaciones,
        'permisos': permisos,
    }


def obtener_estado_configuracion(familiar, adulto_mayor):
    """Devuelve el estado agregado y los puntos pendientes de la configuración."""
    if not verificar_autorizacion_configuracion(familiar, adulto_mayor):
        return {
            'estado': ESTADO_REQUIERE_ATENCION,
            'completa': False,
            'autorizado': False,
            'faltantes': ['No tienes autorización para configurar este dispositivo.'],
            'requiere_atencion': ['Solicita autorización al Adulto mayor o al administrador.'],
            'contactos_activos': 0,
            'notificaciones_validas': False,
            'permisos': [],
        }
    configuracion = obtener_o_crear_configuracion(familiar, adulto_mayor)
    estado = _evaluar_estado(configuracion)
    if not estado['completa'] and configuracion.completado_en:
        configuracion.completado_en = None
        configuracion.completado_por = None
        configuracion.save(update_fields=['completado_en', 'completado_por', 'actualizado_en'])
    return {'autorizado': True, 'configuracion': configuracion, **estado}


def comprobar_configuracion_completa(familiar, adulto_mayor):
    return obtener_estado_configuracion(familiar, adulto_mayor)['completa']


@transaction.atomic
def actualizar_estado_permiso(familiar, adulto_mayor, codigo, estado, origen=EstadoPermiso.Origen.CONFIGURACION_WEB):
    """Actualiza un permiso autenticado; solo el reporte Android puede afirmar concesión."""
    configuracion = obtener_o_crear_configuracion(familiar, adulto_mayor)
    if not isinstance(codigo, str) or not isinstance(estado, str) or not isinstance(origen, str):
        raise ValidationError('El código, estado y origen deben ser valores de texto válidos.')
    permiso = configuracion.permisos.filter(codigo=codigo).first()
    if permiso is None:
        raise ValidationError('El permiso solicitado no forma parte de la configuración.')
    valores_validos = {choice for choice, _ in EstadoPermiso.Estado.choices}
    if estado not in valores_validos:
        raise ValidationError('El estado de permiso no es válido.')
    if origen == EstadoPermiso.Origen.CONFIGURACION_WEB and estado == EstadoPermiso.Estado.CONCEDIDO:
        raise ValidationError('Solo el dispositivo Android puede confirmar que un permiso fue concedido.')
    if origen not in {value for value, _ in EstadoPermiso.Origen.choices}:
        raise ValidationError('El origen del estado no es válido.')

    cambio = permiso.estado != estado or permiso.origen != origen
    permiso.estado = estado
    permiso.origen = origen
    permiso.actualizado_por = familiar
    permiso.save(update_fields=['estado', 'origen', 'actualizado_por', 'actualizado_en'])
    configuracion.actualizado_por = familiar
    configuracion.save(update_fields=['actualizado_por', 'actualizado_en'])
    if cambio and configuracion.completado_en:
        configuracion.completado_en = None
        configuracion.completado_por = None
        configuracion.save(update_fields=['completado_en', 'completado_por', 'actualizado_en'])
    return permiso


def registrar_configuracion_completada(familiar, adulto_mayor):
    configuracion = obtener_o_crear_configuracion(familiar, adulto_mayor)
    estado = _evaluar_estado(configuracion)
    if not estado['completa']:
        return False
    configuracion.actualizado_por = familiar
    configuracion.completado_por = familiar
    configuracion.completado_en = timezone.now()
    configuracion.save(update_fields=['actualizado_por', 'completado_por', 'completado_en', 'actualizado_en'])
    return True
