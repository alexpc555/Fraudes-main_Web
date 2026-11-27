import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import override_settings
from django.urls import reverse

from llamadas.configuracion_services import obtener_estado_configuracion
from llamadas.models import (
    ClasificacionRiesgo,
    ConfiguracionNotificaciones,
    ContactoConfianza,
    EstadoLlamada,
    EventoNotificacion,
    Llamada,
    RelacionFamiliarAdultoMayor,
    TranscripcionLlamada,
)
from llamadas.notificaciones import (
    generar_evento_notificacion,
    guardar_contacto_notificacion,
    obtener_configuracion_notificaciones,
    obtener_contactos_notificacion,
)
from llamadas.services import clasificar_llamada, contestar_llamada_evaluada


User = get_user_model()


@pytest.fixture
def setup_cu21():
    familiar = User.objects.create_user(username='familiar-cu21', password='password')
    adulto = User.objects.create_user(username='adulto-cu21', password='password')
    RelacionFamiliarAdultoMayor.objects.create(familiar=familiar, adulto_mayor=adulto, autorizado=True)
    contacto = ContactoConfianza.objects.create(
        usuario_protegido=adulto,
        nombre='Familiar de confianza',
        numero_telefonico='5512345678',
        correo_electronico='',
        activo=True,
    )
    return familiar, adulto, contacto


@pytest.mark.django_db
def test_selecciona_contacto_activo_y_recupera_configuracion(client, setup_cu21):
    familiar, adulto, contacto = setup_cu21
    client.force_login(familiar)

    response = client.get(reverse('configurar_notificaciones', kwargs={'adulto_id': adulto.pk}))
    assert response.status_code == 200
    assert contacto.nombre in response.content.decode()

    response = client.post(reverse('configurar_notificaciones', kwargs={'adulto_id': adulto.pk}), {
        'contacto_id': str(contacto.pk),
        'confirmar_contacto': 'on',
    })
    assert response.status_code == 302
    config = obtener_configuracion_notificaciones(familiar, adulto)
    assert config.contacto_confianza == contacto
    assert config.familiar_responsable == familiar
    assert obtener_estado_configuracion(familiar, adulto)['notificaciones_validas'] is True

    response = client.get(reverse('configurar_notificaciones', kwargs={'adulto_id': adulto.pk}))
    assert 'Contacto configurado' in response.content.decode()
    assert '5512345678' in response.content.decode()


@pytest.mark.django_db
def test_no_permite_contacto_inexistente_o_sin_confirmar(client, setup_cu21):
    familiar, adulto, contacto = setup_cu21
    client.force_login(familiar)
    url = reverse('configurar_notificaciones', kwargs={'adulto_id': adulto.pk})

    response = client.post(url, {'contacto_id': '999999', 'confirmar_contacto': 'on'})
    assert response.status_code == 200
    assert 'no existe o está inactivo' in response.content.decode()
    assert not ConfiguracionNotificaciones.objects.filter(adulto_mayor=adulto).exists()

    response = client.post(url, {'contacto_id': str(contacto.pk)})
    assert response.status_code == 200
    assert 'Confirma el contacto' in response.content.decode()
    assert not ConfiguracionNotificaciones.objects.filter(adulto_mayor=adulto).exists()


@pytest.mark.django_db
def test_no_hay_contactos_muestra_acceso_a_cu19(client, setup_cu21):
    familiar, adulto, contacto = setup_cu21
    contacto.delete()
    client.force_login(familiar)

    response = client.get(reverse('configurar_notificaciones', kwargs={'adulto_id': adulto.pk}))

    assert response.status_code == 200
    assert 'Agrega primero un contacto activo' in response.content.decode()
    assert reverse('configuracion_contactos', kwargs={'adulto_id': adulto.pk}) in response.content.decode()
    assert list(obtener_contactos_notificacion(familiar, adulto)) == []


@pytest.mark.django_db
def test_familiar_no_autorizado_no_consulta_ni_modifica_configuracion(setup_cu21):
    _, adulto, contacto = setup_cu21
    intruso = User.objects.create_user(username='intruso-cu21', password='password')

    with pytest.raises(PermissionDenied):
        obtener_contactos_notificacion(intruso, adulto)
    with pytest.raises(PermissionDenied):
        guardar_contacto_notificacion(intruso, adulto, contacto.pk, confirmar=True)
    assert not ConfiguracionNotificaciones.objects.filter(adulto_mayor=adulto).exists()


@pytest.mark.django_db
def test_llamada_roja_crea_evento_push_pendiente_sin_exponer_texto_sensible(setup_cu21):
    familiar, adulto, contacto = setup_cu21
    guardar_contacto_notificacion(familiar, adulto, contacto.pk, confirmar=True)
    llamada = Llamada.objects.create(numero_telefonico='5522223333', usuario_protegido=adulto)
    TranscripcionLlamada.objects.create(
        llamada=llamada,
        texto_transcrito='Necesito su contraseña supersecreto123 y código de verificación.',
        estado='COMPLETADO',
    )

    riesgo = clasificar_llamada(llamada)

    assert riesgo.nivel == 'ROJO'
    evento = EventoNotificacion.objects.get(llamada=llamada, tipo=EventoNotificacion.Tipo.RIESGO_ALTO)
    assert evento.estado == EventoNotificacion.Estado.PENDIENTE
    assert evento.canal == EventoNotificacion.Canal.ANDROID_PUSH
    assert evento.numero_origen == '5522223333'
    assert llamada.identificador in evento.mensaje
    assert 'supersecreto123' not in evento.mensaje
    assert 'código de verificación' not in evento.mensaje.lower()
    assert evento.fecha_envio is None
    assert 'FCM no está configurado' in evento.detalle_envio

    clasificar_llamada(llamada)
    assert EventoNotificacion.objects.filter(llamada=llamada, tipo=EventoNotificacion.Tipo.RIESGO_ALTO).count() == 1


@pytest.mark.django_db
def test_aceptar_llamada_amarilla_genera_evento_para_contacto_familiar(setup_cu21):
    familiar, adulto, contacto = setup_cu21
    guardar_contacto_notificacion(familiar, adulto, contacto.pk, confirmar=True)
    llamada = Llamada.objects.create(numero_telefonico='5533334444', usuario_protegido=adulto)
    riesgo = ClasificacionRiesgo.objects.create(
        llamada=llamada,
        nivel='AMARILLO',
        puntuacion=42,
        motivo='Verifica por un canal oficial.',
        es_actual=True,
    )

    contestar_llamada_evaluada(llamada)

    evento = EventoNotificacion.objects.get(llamada=llamada, tipo=EventoNotificacion.Tipo.LLAMADA_ACEPTADA)
    assert evento.nivel_riesgo == riesgo.nivel
    assert evento.contacto_confianza == contacto
    assert evento.estado == EventoNotificacion.Estado.PENDIENTE
    assert llamada.estado == EstadoLlamada.PERMITIDA


@pytest.mark.django_db
def test_error_del_adaptador_queda_registrado(setup_cu21):
    familiar, adulto, contacto = setup_cu21
    guardar_contacto_notificacion(familiar, adulto, contacto.pk, confirmar=True)
    llamada = Llamada.objects.create(numero_telefonico='5544445555', usuario_protegido=adulto)
    riesgo = ClasificacionRiesgo.objects.create(llamada=llamada, nivel='ROJO', puntuacion=90, es_actual=True)

    class AdaptadorFallido:
        def enviar(self, evento):
            raise RuntimeError('Proveedor temporalmente fuera de servicio')

    eventos = generar_evento_notificacion(
        llamada,
        tipo=EventoNotificacion.Tipo.RIESGO_ALTO,
        clasificacion=riesgo,
        adaptadores={EventoNotificacion.Canal.ANDROID_PUSH: AdaptadorFallido()},
    )

    assert len(eventos) == 1
    evento = eventos[0]
    assert evento.estado == EventoNotificacion.Estado.ERROR
    assert 'fuera de servicio' in evento.error_detalle
    assert evento.fecha_ultimo_intento is not None
    assert evento.fecha_envio is None


@pytest.mark.django_db
def test_contacto_desactivado_no_se_puede_guardar(client, setup_cu21):
    familiar, adulto, contacto = setup_cu21
    contacto.activo = False
    contacto.save()
    client.force_login(familiar)

    response = client.post(reverse('configurar_notificaciones', kwargs={'adulto_id': adulto.pk}), {
        'contacto_id': str(contacto.pk), 'confirmar_contacto': 'on',
    })

    assert response.status_code == 200
    assert 'no existe o está inactivo' in response.content.decode()
    assert not ConfiguracionNotificaciones.objects.filter(adulto_mayor=adulto).exists()


@pytest.mark.django_db
@override_settings(
    NOTIFICACIONES_EMAIL_ACTIVAS=True,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_HOST='smtp.example.test',
)
def test_correo_solo_se_envia_con_configuracion_opt_in(setup_cu21):
    familiar, adulto, contacto = setup_cu21
    contacto.correo_electronico = 'contacto@example.test'
    contacto.save()
    guardar_contacto_notificacion(familiar, adulto, contacto.pk, confirmar=True)
    llamada = Llamada.objects.create(numero_telefonico='5566667777', usuario_protegido=adulto)
    riesgo = ClasificacionRiesgo.objects.create(llamada=llamada, nivel='ROJO', puntuacion=90, es_actual=True)

    eventos = generar_evento_notificacion(llamada, tipo=EventoNotificacion.Tipo.RIESGO_ALTO, clasificacion=riesgo)

    correo = EventoNotificacion.objects.get(llamada=llamada, canal=EventoNotificacion.Canal.CORREO)
    assert correo.estado == EventoNotificacion.Estado.ENVIADA
    assert correo.fecha_envio is not None
    assert len(eventos) == 2
