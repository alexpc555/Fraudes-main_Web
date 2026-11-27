import pytest
import json
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from llamadas.configuracion_services import (
    ESTADO_COMPLETA,
    ESTADO_INCOMPLETA,
    ESTADO_REQUIERE_ATENCION,
    actualizar_estado_permiso,
    comprobar_configuracion_completa,
    obtener_estado_configuracion,
)
from llamadas.models import (
    ConfiguracionAplicacion,
    ContactoConfianza,
    EstadoPermiso,
    RelacionFamiliarAdultoMayor,
)
from llamadas.notificaciones import guardar_contacto_notificacion


User = get_user_model()


@pytest.fixture
def personas():
    familiar = User.objects.create_user(username='familiar-cu20', password='clave-segura')
    adulto = User.objects.create_user(username='adulto-cu20', password='clave-segura')
    RelacionFamiliarAdultoMayor.objects.create(familiar=familiar, adulto_mayor=adulto, autorizado=True)
    return familiar, adulto


@pytest.mark.django_db
def test_familiar_autorizado_puede_abrir_asistente_y_estados_inician_pendientes(client, personas):
    familiar, adulto = personas
    client.force_login(familiar)

    response = client.get(reverse('configuracion_aplicacion', kwargs={'adulto_id': adulto.pk}))

    assert response.status_code == 200
    assert 'Configuración inicial' in response.content.decode()
    assert ConfiguracionAplicacion.objects.filter(adulto_mayor=adulto).exists()
    assert EstadoPermiso.objects.filter(configuracion__adulto_mayor=adulto, estado=EstadoPermiso.Estado.PENDIENTE).count() == 3


@pytest.mark.django_db
def test_familiar_no_autorizado_no_puede_configurar_ni_crear_estados(client):
    familiar = User.objects.create_user(username='familiar-no-autorizado', password='clave-segura')
    adulto = User.objects.create_user(username='adulto-sin-relacion', password='clave-segura')
    client.force_login(familiar)

    response = client.get(reverse('configuracion_aplicacion', kwargs={'adulto_id': adulto.pk}))

    assert response.status_code == 403
    assert 'No puedes hacer cambios' in response.content.decode()
    assert not ConfiguracionAplicacion.objects.filter(adulto_mayor=adulto).exists()
    assert obtener_estado_configuracion(familiar, adulto)['estado'] == ESTADO_REQUIERE_ATENCION
    with pytest.raises(PermissionDenied):
        actualizar_estado_permiso(familiar, adulto, 'notificaciones', EstadoPermiso.Estado.DENEGADO)


@pytest.mark.django_db
def test_solo_un_familiar_puede_tener_autorizacion_activa_por_adulto(personas):
    _, adulto = personas
    otro_familiar = User.objects.create_user(username='segundo-familiar', password='clave-segura')

    with pytest.raises(IntegrityError), transaction.atomic():
        RelacionFamiliarAdultoMayor.objects.create(
            familiar=otro_familiar,
            adulto_mayor=adulto,
            autorizado=True,
        )


@pytest.mark.django_db
def test_permisos_pendientes_se_muestran_y_web_no_puede_confirmar_concesion(client, personas):
    familiar, adulto = personas
    client.force_login(familiar)
    response = client.get(reverse('configuracion_aplicacion', kwargs={'adulto_id': adulto.pk}) + '?paso=permisos')

    assert response.status_code == 200
    assert 'Pendiente de solicitar' in response.content.decode()
    permiso = EstadoPermiso.objects.get(configuracion__adulto_mayor=adulto, codigo='notificaciones')
    with pytest.raises(ValidationError):
        actualizar_estado_permiso(familiar, adulto, permiso.codigo, EstadoPermiso.Estado.CONCEDIDO)
    permiso.refresh_from_db()
    assert permiso.estado == EstadoPermiso.Estado.PENDIENTE


@pytest.mark.django_db
def test_asistente_reutiliza_contactos_existentes_del_adulto_mayor(client, personas):
    familiar, adulto = personas
    contacto = ContactoConfianza.objects.create(
        usuario_protegido=adulto,
        nombre='María López',
        numero_telefonico='+52 55 1234 5678',
        relacion='Hija',
    )
    client.force_login(familiar)

    response = client.get(reverse('configuracion_aplicacion', kwargs={'adulto_id': adulto.pk}) + '?paso=contactos')

    assert response.status_code == 200
    assert 'María López' in response.content.decode()
    assert '1 contacto(s) de confianza activo(s)' in response.content.decode()
    response = client.get(reverse('configuracion_contactos', kwargs={'adulto_id': adulto.pk}))
    assert response.status_code == 302
    response = client.get(reverse('lista_contactos'))
    assert response.status_code == 200
    assert 'María López' in response.content.decode()
    assert ContactoConfianza.objects.filter(usuario_protegido=adulto).count() == 1
    assert ContactoConfianza.objects.get(pk=contacto.pk).usuario_protegido == adulto


@pytest.mark.django_db
def test_familiar_autorizado_agrega_edita_y_elimina_en_la_agenda_existente(client, personas):
    familiar, adulto = personas
    client.force_login(familiar)
    client.get(reverse('configuracion_contactos', kwargs={'adulto_id': adulto.pk}))
    response = client.post(reverse('contacto_crear'), {
        'nombre': 'Carlos',
        'numero_telefonico': '5512345678',
        'relacion': 'Hijo',
        'descripcion': 'Contacto principal',
        'activo': 'on',
    })
    assert response.status_code == 302
    contacto = ContactoConfianza.objects.get(usuario_protegido=adulto)
    assert contacto.nombre == 'Carlos'

    response = client.post(reverse('contacto_editar', kwargs={'pk': contacto.pk}), {
        'nombre': 'Carlos Pérez',
        'numero_telefonico': '5512345678',
        'relacion': 'Hijo',
        'descripcion': 'Actualizado',
        'activo': 'on',
    })
    assert response.status_code == 302
    contacto.refresh_from_db()
    assert contacto.nombre == 'Carlos Pérez'
    configuracion = ConfiguracionAplicacion.objects.get(adulto_mayor=adulto)
    assert configuracion.actualizado_por == familiar

    response = client.post(reverse('contacto_eliminar', kwargs={'pk': contacto.pk}))
    assert response.status_code == 302
    assert not ContactoConfianza.objects.filter(pk=contacto.pk).exists()


@pytest.mark.django_db
def test_familiar_sin_autorizacion_no_puede_editar_contacto_de_adulto(client):
    familiar = User.objects.create_user(username='familiar-contacto-no-autorizado', password='clave-segura')
    adulto = User.objects.create_user(username='adulto-contacto-protegido', password='clave-segura')
    contacto = ContactoConfianza.objects.create(usuario_protegido=adulto, nombre='Contacto', numero_telefonico='5512345678')
    client.force_login(familiar)
    session = client.session
    session['cu20_adulto_mayor_id'] = adulto.pk
    session.save()

    response = client.post(reverse('contacto_eliminar', kwargs={'pk': contacto.pk}))

    assert response.status_code == 403
    assert ContactoConfianza.objects.filter(pk=contacto.pk).exists()


@pytest.mark.django_db
def test_configuracion_completa_solo_con_permisos_esenciales_contactos_y_notificaciones(client, personas):
    familiar, adulto = personas
    estado_inicial = obtener_estado_configuracion(familiar, adulto)
    configuracion = estado_inicial['configuracion']
    assert estado_inicial['estado'] == ESTADO_INCOMPLETA
    contacto = ContactoConfianza.objects.create(usuario_protegido=adulto, nombre='Hijo', numero_telefonico='5512345678')
    guardar_contacto_notificacion(familiar, adulto, contacto.pk, confirmar=True)
    configuracion.notificaciones_habilitadas = True
    configuracion.save(update_fields=['notificaciones_habilitadas', 'actualizado_en'])
    for codigo in ('notificaciones', 'identificacion_llamadas'):
        actualizar_estado_permiso(
            familiar,
            adulto,
            codigo,
            EstadoPermiso.Estado.CONCEDIDO,
            origen=EstadoPermiso.Origen.DISPOSITIVO_ANDROID,
        )

    assert comprobar_configuracion_completa(familiar, adulto)
    estado = obtener_estado_configuracion(familiar, adulto)
    assert estado['estado'] == ESTADO_COMPLETA
    client.force_login(familiar)
    response = client.post(reverse('configuracion_aplicacion', kwargs={'adulto_id': adulto.pk}), {
        'paso': 'confirmacion', 'accion': 'finalizar',
    })
    assert response.status_code == 302
    configuracion.refresh_from_db()
    assert configuracion.completado_por == familiar
    assert configuracion.completado_en is not None


@pytest.mark.django_db
def test_permiso_esencial_denegado_requiere_atencion_y_errores_no_completan(personas):
    familiar, adulto = personas
    obtener_estado_configuracion(familiar, adulto)
    actualizar_estado_permiso(familiar, adulto, 'notificaciones', EstadoPermiso.Estado.DENEGADO)

    assert obtener_estado_configuracion(familiar, adulto)['estado'] == ESTADO_REQUIERE_ATENCION
    assert not comprobar_configuracion_completa(familiar, adulto)
    configuracion = ConfiguracionAplicacion.objects.get(adulto_mayor=adulto)
    assert configuracion.completado_en is None


@pytest.mark.django_db
def test_android_reporta_estado_real_por_endpoint_autorizado(client, personas):
    familiar, adulto = personas
    client.force_login(familiar)
    url = reverse('api_reportar_estado_permiso', kwargs={'adulto_id': adulto.pk})

    response = client.post(url, data=json.dumps({
        'codigo': 'notificaciones',
        'estado': EstadoPermiso.Estado.CONCEDIDO,
    }), content_type='application/json')

    assert response.status_code == 200
    assert response.json()['origen'] == EstadoPermiso.Origen.DISPOSITIVO_ANDROID
    permiso = EstadoPermiso.objects.get(configuracion__adulto_mayor=adulto, codigo='notificaciones')
    assert permiso.estado == EstadoPermiso.Estado.CONCEDIDO


@pytest.mark.django_db
def test_reporte_android_rechaza_estado_invalido(client, personas):
    familiar, adulto = personas
    client.force_login(familiar)

    response = client.post(reverse('api_reportar_estado_permiso', kwargs={'adulto_id': adulto.pk}), {
        'codigo': 'notificaciones',
        'estado': 'CONCEDIDO_POR_MAGIC',
    }, content_type='application/json')

    assert response.status_code == 400
    assert not ConfiguracionAplicacion.objects.filter(adulto_mayor=adulto, completado_en__isnull=False).exists()
