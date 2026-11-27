import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from llamadas.contenido_ayuda import TEMAS_AYUDA
from llamadas.models import Llamada, RelacionFamiliarAdultoMayor


User = get_user_model()


@pytest.mark.django_db
def test_ayuda_muestra_lista_completa_de_temas(client):
    response = client.get(reverse('ayuda'))

    assert response.status_code == 200
    contenido = response.content.decode()
    assert '<h1 class="mt-1 text-3xl font-extrabold text-brand-navy">Ayuda</h1>' in contenido
    for tema in TEMAS_AYUDA:
        assert tema['titulo'] in contenido
    assert len(TEMAS_AYUDA) == 10


@pytest.mark.django_db
@pytest.mark.parametrize('tema', [tema['slug'] for tema in TEMAS_AYUDA])
def test_se_puede_abrir_individualmente_cada_tema(client, tema):
    response = client.get(reverse('ayuda_tema', kwargs={'tema': tema}))

    assert response.status_code == 200
    assert TEMAS_AYUDA[[item['slug'] for item in TEMAS_AYUDA].index(tema)]['titulo'] in response.content.decode()
    assert 'Regresar a temas' in response.content.decode()
    assert 'Salir de Ayuda' in response.content.decode()


@pytest.mark.django_db
def test_navegacion_regresa_a_temas_abre_otro_y_sale_a_pantalla_anterior(client):
    volver = '/contactos/?q=Ana'
    response = client.get(reverse('ayuda_tema', kwargs={'tema': 'permisos'}), {'volver': volver})
    contenido = response.content.decode()

    assert response.status_code == 200
    assert f'href="{reverse("ayuda")}?volver=/contactos/%3Fq%3DAna"' in contenido
    assert f'href="{volver}"' in contenido
    response = client.get(reverse('ayuda_tema', kwargs={'tema': 'contactos'}), {'volver': volver})
    assert 'Contactos de confianza' in response.content.decode()


@pytest.mark.django_db
def test_ayuda_sin_tema_seleccionado_no_falla_y_regresa_al_panel(client):
    response = client.get(reverse('ayuda'))

    assert response.status_code == 200
    assert f'href="{reverse("administrar_llamadas")}"' in response.content.decode()


@pytest.mark.django_db
def test_tema_desconocido_muestra_lista_y_no_rompe_navegacion(client):
    response = client.get('/ayuda/tema-que-no-existe/')

    assert response.status_code == 404
    assert 'No encontramos ese tema' in response.content.decode()
    assert 'Configuración inicial' in response.content.decode()


@pytest.mark.django_db
def test_accesos_contextuales_desde_pantallas_principales(client):
    dashboard = client.get(reverse('administrar_llamadas'))
    assert reverse('ayuda') in dashboard.content.decode()
    contactos = client.get(reverse('lista_contactos'))
    assert reverse('ayuda_tema', kwargs={'tema': 'contactos'}) in contactos.content.decode()

    familiar = User.objects.create_user(username='familiar-ayuda', password='password')
    adulto = User.objects.create_user(username='adulto-ayuda', password='password')
    RelacionFamiliarAdultoMayor.objects.create(familiar=familiar, adulto_mayor=adulto, autorizado=True)
    client.force_login(familiar)
    configuracion = client.get(reverse('configuracion_aplicacion', kwargs={'adulto_id': adulto.pk}) + '?paso=permisos')
    assert reverse('ayuda_tema', kwargs={'tema': 'permisos'}) in configuracion.content.decode()
    notificaciones = client.get(reverse('configurar_notificaciones', kwargs={'adulto_id': adulto.pk}))
    assert reverse('ayuda_tema', kwargs={'tema': 'notificaciones-familiares'}) in notificaciones.content.decode()

    llamada = Llamada.objects.create(numero_telefonico='5510101010', usuario_protegido=adulto)
    alerta = client.get(reverse('alerta_riesgo', kwargs={'pk': llamada.pk}))
    assert alerta.status_code == 200
    assert reverse('ayuda_tema', kwargs={'tema': 'niveles-riesgo'}) in alerta.content.decode()


@pytest.mark.django_db
def test_pantalla_de_ayuda_usa_componentes_grandes_y_adaptables(client):
    response = client.get(reverse('ayuda_tema', kwargs={'tema': 'contestar-rechazar'}))
    contenido = response.content.decode()

    assert 'max-w-xl' in contenido
    assert 'min-h-14' in contenido
    assert 'text-base' in contenido


@pytest.mark.django_db
def test_api_expone_el_mismo_contenido_para_futura_app_android(client):
    lista = client.get(reverse('ayuda_api'))
    assert lista.status_code == 200
    assert len(lista.json()['temas']) == 10
    tema = client.get(reverse('ayuda_api_tema', kwargs={'tema': 'niveles-riesgo'}))
    assert tema.status_code == 200
    assert tema.json()['titulo'] == 'Niveles de riesgo'
    assert len(tema.json()['pasos']) >= 3
