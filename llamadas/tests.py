import io
import math
import os
import struct
import wave

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from llamadas.models import (
    AnalisisLlamada,
    ClasificacionRiesgo,
    ContactoConfianza,
    EstadoLlamada,
    IndicadorFraude,
    IntervencionAgente,
    Llamada,
    NumeroReportado,
    PreguntaAsistente,
    ResultadoConsultaNumero,
    RespuestaLlamada,
    ResumenLlamada,
    SesionConversacion,
    TranscripcionLlamada,
)
from llamadas.services import (
    AdaptadorConsultaNumeroExterna,
    AgenteVoz,
    analizar_llamada,
    clasificar_llamada,
    consultar_numero_reportado,
    contestar_llamada_evaluada,
    detectar_indicios_fraude,
    generar_resumen_llamada,
    mostrar_alerta_riesgo,
    realizar_llamada,
    rechazar_llamada_evaluada,
    registrar_llamada,
    verificar_contacto,
)
from llamadas.speech_to_text import transcribir_audio
from llamadas.text_to_speech import generar_audio, reproducir_texto_voz

User = get_user_model()


@pytest.mark.django_db
class TestCU01Llamadas:
    def test_registrar_llamada_desconocida_queda_pendiente(self):
        llamada = registrar_llamada('5522334455')

        assert llamada.pk is not None
        assert llamada.identificador
        assert llamada.numero_telefonico == '5522334455'
        assert llamada.estado == EstadoLlamada.PENDIENTE_DE_EVALUACION
        assert llamada.resultado_evaluacion == ''

    def test_modelo_rechaza_numero_invalido(self):
        with pytest.raises(ValidationError):
            llamada = Llamada(numero_telefonico='abc')
            llamada.full_clean()

    def test_busqueda_y_filtro_por_estado(self):
        Llamada.objects.create(numero_telefonico='5511111111', estado=EstadoLlamada.FINALIZADA)
        Llamada.objects.create(numero_telefonico='5522222222', estado=EstadoLlamada.PENDIENTE_DE_EVALUACION)

        resultados = Llamada.objects.filter(estado=EstadoLlamada.PENDIENTE_DE_EVALUACION)
        assert resultados.count() == 1
        assert Llamada.objects.filter(numero_telefonico__icontains='222').count() == 1

    def test_panel_administrativo_muestra_llamadas(self):
        Llamada.objects.create(numero_telefonico='5511111111', estado=EstadoLlamada.PENDIENTE_DE_EVALUACION)
        client = Client()

        response = client.get(reverse('administrar_llamadas'))

        assert response.status_code == 200
        assert 'Panel de llamadas' in response.content.decode('utf-8')
        assert '5511111111' in response.content.decode('utf-8')

    def test_formulario_registra_llamada_via_vista(self):
        client = Client()

        response = client.post('/registrar/', {'numero_telefonico': '5544332211'})

        assert response.status_code == 302
        llamada = Llamada.objects.get(numero_telefonico='5544332211')
        assert llamada.estado == EstadoLlamada.PENDIENTE_DE_EVALUACION
        assert llamada.identificador


@pytest.mark.django_db
class TestCU02ContactosConfianza:
    def test_verificacion_contacto_confiable(self):
        usuario = User.objects.create_user(username='protegido', password='secret123')
        ContactoConfianza.objects.create(
            usuario_protegido=usuario,
            nombre='María',
            numero_telefonico='+52 55 1234 5678',
            activo=True,
        )

        assert verificar_contacto('5512345678') is True

    def test_verificacion_contacto_desconocido(self):
        assert verificar_contacto('5566677788') is False

    def test_verificacion_contacto_inactivo(self):
        usuario = User.objects.create_user(username='protegido2', password='secret123')
        ContactoConfianza.objects.create(
            usuario_protegido=usuario,
            nombre='Luis',
            numero_telefonico='5511223344',
            activo=False,
        )

        assert verificar_contacto('5511223344') is False

    def test_verificacion_contacto_oculto_no_es_confiable(self):
        assert verificar_contacto('0000000000') is False

    def test_registrar_llamada_con_contacto_activo_queda_permitida(self):
        usuario = User.objects.create_user(username='protegido3', password='secret123')
        ContactoConfianza.objects.create(
            usuario_protegido=usuario,
            nombre='Ana',
            numero_telefonico='5522334455',
            activo=True,
        )

        llamada = registrar_llamada('5522334455')

        assert llamada.estado == EstadoLlamada.PERMITIDA


@pytest.mark.django_db
class TestCU03NumerosReportados:
    def test_consulta_numero_reportado_recupera_antecedentes(self):
        NumeroReportado.objects.create(
            numero_telefonico='+52 55 1234 5678',
            identidad_reportada='Fraudster Inc.',
            descripcion='Actividades sospechosas',
            tipo_incidente='fraude',
            cantidad_reportes=3,
        )

        resultado = consultar_numero_reportado('5512345678')

        assert resultado.estado == 'REPORTADO'
        assert resultado.numero_reportado is not None
        assert resultado.identidad_reportada == 'Fraudster Inc.'

    def test_consulta_numero_no_reportado_registra_sin_antecedentes(self):
        resultado = consultar_numero_reportado('5544332211')

        assert resultado.estado == 'SIN_ANTECEDENTES'
        assert resultado.descripcion == 'No existen antecedentes reportados para este número.'

    def test_error_en_consulta_registra_error_y_permite_continuar(self, monkeypatch):
        def lanzar_error(self, numero):
            raise RuntimeError('API no disponible')

        monkeypatch.setattr(AdaptadorConsultaNumeroExterna, 'consultar', lanzar_error)

        resultado = consultar_numero_reportado('5511111111')

        assert resultado.estado == 'ERROR'
        assert 'API no disponible' in resultado.error_detalle

    def test_registrar_llamada_desconocida_consulta_antecedentes_sin_cambiar_estado(self):
        NumeroReportado.objects.create(
            numero_telefonico='5522334455',
            identidad_reportada='Proveedor sospechoso',
            descripcion='Llamadas repetidas',
            tipo_incidente='suplantacion',
            cantidad_reportes=2,
        )

        llamada = registrar_llamada('5522334455')

        assert llamada.estado == EstadoLlamada.PENDIENTE_DE_EVALUACION
        assert llamada.consultas_numero.count() == 1
        assert llamada.consultas_numero.first().estado == 'REPORTADO'

    def test_registrar_llamada_con_contacto_activo_no_consulta_reportados(self):
        usuario = User.objects.create_user(username='protegido4', password='secret123')
        ContactoConfianza.objects.create(
            usuario_protegido=usuario,
            nombre='Beto',
            numero_telefonico='5577889900',
            activo=True,
        )
        NumeroReportado.objects.create(
            numero_telefonico='5577889900',
            identidad_reportada='No debe consultarse',
            descripcion='Ignorado al ser contacto',
            tipo_incidente='fraude',
            cantidad_reportes=1,
        )

        llamada = registrar_llamada('5577889900')

        assert llamada.estado == EstadoLlamada.PERMITIDA
        assert llamada.consultas_numero.count() == 0


@pytest.mark.django_db
class TestCU04ProcesarVozATexto:
    @staticmethod
    def _generar_audio_wav(segundos=0.2, frecuencia=440.0):
        sample_rate = 8000
        total_samples = int(sample_rate * segundos)
        payload = bytearray()
        for i in range(total_samples):
            value = int(32767 * 0.15 * math.sin(2 * math.pi * frecuencia * i / sample_rate))
            payload.extend(struct.pack('<h', value))

        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(bytes(payload))
        return SimpleUploadedFile('llamada.wav', buffer.getvalue(), content_type='audio/wav')

    def test_crea_transcripcion_de_llamada_con_audio(self, monkeypatch):
        llamada = Llamada.objects.create(numero_telefonico='5512345678')

        monkeypatch.setattr(
            'llamadas.views.transcribir_audio',
            lambda archivo: {
                'texto': 'Hola, necesito ayuda',
                'confianza': 0.87,
                'duracion_audio': 0.2,
                'estado': 'COMPLETADO',
            },
        )
        audio = self._generar_audio_wav()

        client = Client()
        response = client.post(
            reverse('procesar_audio_llamada', kwargs={'pk': llamada.pk}),
            {'audio': audio, 'pregunta_asociada': '¿Qué solicitó?', 'orden': 1},
        )

        assert response.status_code == 302
        transcripcion = TranscripcionLlamada.objects.get(llamada=llamada)
        assert transcripcion.texto_transcrito == 'Hola, necesito ayuda'
        assert transcripcion.estado == 'COMPLETADO'
        assert transcripcion.pregunta_asociada == '¿Qué solicitó?'

    def test_no_inventa_transcripcion_si_el_audio_no_es_inteligible(self):
        wav_bytes = io.BytesIO()
        with wave.open(wav_bytes, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(8000)
            wav_file.writeframes(b'\x00\x00' * 8000)

        archivo = SimpleUploadedFile('silencio.wav', wav_bytes.getvalue(), content_type='audio/wav')
        resultado = transcribir_audio(archivo)

        assert resultado['estado'] == 'AUDIO_NO_INTELIGIBLE'
        assert resultado['texto'] == ''

    def test_detalle_llamada_muestra_transcripciones(self):
        llamada = Llamada.objects.create(numero_telefonico='5512345678')
        TranscripcionLlamada.objects.create(
            llamada=llamada,
            texto_transcrito='Necesito ayuda urgente',
            estado='COMPLETADO',
            pregunta_asociada='¿Cuál es el problema?',
        )

        response = Client().get(reverse('detalle_llamada', kwargs={'pk': llamada.pk}))

        assert response.status_code == 200
        contenido = response.content.decode('utf-8')
        assert 'Transcripciones de audio' in contenido
        assert 'Necesito ayuda urgente' in contenido


@pytest.mark.django_db
class TestCU05IdentificarMotivoDeLlamada:
    def test_analiza_llamada_legitima_y_la_clasifica_como_segura(self):
        llamada = Llamada.objects.create(numero_telefonico='5511111111')
        for codigo, respuesta in {
            'nombre': 'Luis García, quiero hablar con Ana López',
            'institucion': 'Banco del Estado de México',
            'motivo': 'Solicito información sobre mi tarjeta de crédito',
            'solicita_datos_personales': 'No, solo quiero confirmar información general',
            'solicita_pago': 'No, no realizo ninguna transferencia ni pago',
        }.items():
            pregunta_obj, _ = PreguntaAsistente.objects.get_or_create(
                codigo=codigo,
                defaults={'texto': 'Pregunta', 'orden': 1},
            )
            RespuestaLlamada.objects.create(llamada=llamada, pregunta=pregunta_obj, texto_respuesta=respuesta)

        analisis = analizar_llamada(llamada)

        assert analisis.clasificacion == 'SEGURO'
        assert analisis.identidad_declarada == 'Luis García'
        assert analisis.institucion == 'Banco del Estado de México'
        assert 'sin indicadores importantes' in analisis.explicacion.lower()

    def test_analiza_llamada_sospechosa_y_la_clasifica_como_alerta(self):
        llamada = Llamada.objects.create(numero_telefonico='5522222222')
        for codigo, respuesta in {
            'nombre': 'Pedro Ruiz, necesito hablar con Atención al Cliente',
            'institucion': 'Mi banco',
            'motivo': 'Necesito que me ayude con mi cuenta',
            'solicita_datos_personales': 'Sí, necesito mi contraseña y código de seguridad',
            'solicita_pago': 'Sí, hoy mismo tengo que transferir dinero',
        }.items():
            pregunta_obj, _ = PreguntaAsistente.objects.get_or_create(
                codigo=codigo,
                defaults={'texto': 'Pregunta', 'orden': 1},
            )
            RespuestaLlamada.objects.create(llamada=llamada, pregunta=pregunta_obj, texto_respuesta=respuesta)

        analisis = analizar_llamada(llamada)

        assert analisis.clasificacion == 'ALERTA'
        assert analisis.solicitud_contrasenas is True
        assert 'transferencia' in analisis.indicadores_detectados.lower()

    def test_analiza_llamada_incompleta_y_registra_informacion_insuficiente(self):
        llamada = Llamada.objects.create(numero_telefonico='5533333333')
        pregunta, _ = PreguntaAsistente.objects.get_or_create(
            codigo='nombre',
            defaults={'texto': 'Pregunta', 'orden': 1},
        )
        RespuestaLlamada.objects.create(
            llamada=llamada,
            pregunta=pregunta,
            texto_respuesta='',
        )

        analisis = analizar_llamada(llamada)

        assert analisis.clasificacion == 'INFORMACION_INSUFICIENTE'
        assert 'incertidumbre' in analisis.explicacion.lower() or 'falta' in analisis.explicacion.lower()

    def test_resultado_analisis_muestra_decision_final_del_adulto_mayor(self):
        llamada = Llamada.objects.create(numero_telefonico='5544444444')
        pregunta, _ = PreguntaAsistente.objects.get_or_create(
            codigo='nombre',
            defaults={'texto': 'Pregunta', 'orden': 1},
        )
        RespuestaLlamada.objects.create(llamada=llamada, pregunta=pregunta, texto_respuesta='Marta López')

        analisis = analizar_llamada(llamada)
        analisis.decision_adulto_mayor = 'ACEPTAR'
        analisis.save()

        response = Client().post(
            reverse('decidir_llamada', kwargs={'pk': analisis.pk}),
            {'decision': 'ACEPTAR'},
        )

        assert response.status_code == 302
        analisis.refresh_from_db()
        assert analisis.decision_adulto_mayor == 'ACEPTAR'


@pytest.mark.django_db
class TestCU06DetectarIndiciosFraude:
    def test_detecta_solicitud_de_codigo_de_seguridad(self):
        llamada = Llamada.objects.create(numero_telefonico='5511223344')
        transcripcion = TranscripcionLlamada.objects.create(
            llamada=llamada,
            texto_transcrito='Necesito ayuda con mi cuenta. Por favor, deme su contraseña y código de seguridad.',
            estado='COMPLETADO',
        )

        indicadores = detectar_indicios_fraude(transcripcion)

        assert indicadores.exists()
        assert IndicadorFraude.objects.filter(llamada=llamada).count() >= 2
        assert any('contraseña' in item.fragmento.lower() for item in IndicadorFraude.objects.filter(llamada=llamada))

    def test_no_inventa_indicios_si_no_hay_evidencia_valida(self):
        llamada = Llamada.objects.create(numero_telefonico='5522334455')
        transcripcion = TranscripcionLlamada.objects.create(
            llamada=llamada,
            texto_transcrito='Hola, quería hablar con alguien.',
            estado='COMPLETADO',
        )

        indicadores = detectar_indicios_fraude(transcripcion)

        assert indicadores.count() == 0


@pytest.mark.django_db
class TestCU07ClasificarLlamada:
    def test_clasifica_llamada_verde_cuando_no_hay_indicios(self):
        llamada = Llamada.objects.create(numero_telefonico='5533445566')
        TranscripcionLlamada.objects.create(
            llamada=llamada,
            texto_transcrito='Quiero confirmar una cita y no necesito información personal.',
            estado='COMPLETADO',
        )

        clasificacion = clasificar_llamada(llamada)

        assert clasificacion.nivel == 'VERDE'
        assert clasificacion.puntuacion >= 0

    def test_clasifica_llamada_amarilla_con_informacion_incompleta(self):
        llamada = Llamada.objects.create(numero_telefonico='5544556677')
        TranscripcionLlamada.objects.create(
            llamada=llamada,
            texto_transcrito='Necesito revisar mi cuenta. Por favor, dígame si es usted el banco.',
            estado='COMPLETADO',
        )

        clasificacion = clasificar_llamada(llamada)

        assert clasificacion.nivel == 'AMARILLO'
        assert 'información' in clasificacion.motivo.lower() or 'precaución' in clasificacion.motivo.lower()

    def test_clasifica_llamada_roja_cuando_hay_indicios_claros(self):
        llamada = Llamada.objects.create(numero_telefonico='5555667788')
        TranscripcionLlamada.objects.create(
            llamada=llamada,
            texto_transcrito='Necesito su contraseña, CVV y código de verificación hoy mismo, o de lo contrario se bloqueará su cuenta.',
            estado='COMPLETADO',
        )

        clasificacion = clasificar_llamada(llamada)

        assert clasificacion.nivel == 'ROJO'
        assert 'PELIGRO' in clasificacion.motivo.upper()


@pytest.mark.django_db
class TestCU17ResumenLlamada:
    def test_generar_resumen_con_identidad_desconocida(self):
        llamada = Llamada.objects.create(numero_telefonico='5551112233')
        for codigo, respuesta in {
            'nombre': '',
            'institucion': 'Banco de Crédito',
            'motivo': 'Necesito ayuda con mi cuenta',
            'solicita_datos_personales': 'Sí, necesito mi contraseña',
            'solicita_pago': 'No',
        }.items():
            pregunta, _ = PreguntaAsistente.objects.get_or_create(
                codigo=codigo,
                defaults={'texto': 'Pregunta', 'orden': 1},
            )
            RespuestaLlamada.objects.create(llamada=llamada, pregunta=pregunta, texto_respuesta=respuesta)

        resumen = generar_resumen_llamada(llamada)

        assert resumen.identidad_declarada == 'No identificado'
        assert 'No identificado' in resumen.texto_resumen
        assert 'contraseña' in resumen.texto_resumen.lower()

    def test_generar_resumen_con_motivo_incompleto(self):
        llamada = Llamada.objects.create(numero_telefonico='5562223344')
        for codigo, respuesta in {
            'nombre': 'Lucía Gómez',
            'institucion': 'Seguros Vida',
            'motivo': '',
            'solicita_datos_personales': 'No',
            'solicita_pago': 'No',
        }.items():
            pregunta, _ = PreguntaAsistente.objects.get_or_create(
                codigo=codigo,
                defaults={'texto': 'Pregunta', 'orden': 1},
            )
            RespuestaLlamada.objects.create(llamada=llamada, pregunta=pregunta, texto_respuesta=respuesta)

        resumen = generar_resumen_llamada(llamada)

        assert resumen.motivo == 'No se pudo determinar el motivo de la llamada'
        assert 'No se pudo determinar el motivo de la llamada' in resumen.texto_resumen
        assert resumen.nivel_riesgo == 'BAJO'

    def test_generar_resumen_con_niveles_de_riesgo(self):
        for nivel, respuesta in {
            'SEGURO': {
                'nombre': 'Ana Torres',
                'institucion': 'Banco del Sur',
                'motivo': 'Quiero confirmar mi cita',
                'solicita_datos_personales': 'No',
                'solicita_pago': 'No',
            },
            'INTERMEDIO': {
                'nombre': 'Roberto Díaz',
                'institucion': 'Aseguradora',
                'motivo': 'Necesito revisar mi póliza',
                'solicita_datos_personales': 'Tal vez necesito confirmar mi dirección',
                'solicita_pago': 'No',
            },
            'ALERTA': {
                'nombre': 'Sofía Rojas',
                'institucion': 'Banco Estatal',
                'motivo': 'Hay un problema con su cuenta',
                'solicita_datos_personales': 'Sí, necesito mi contraseña y un código de seguridad',
                'solicita_pago': 'Sí, necesito transferir dinero hoy mismo',
            },
        }.items():
            llamada = Llamada.objects.create(numero_telefonico=f'55{abs(hash(nivel)) % 100000000:08d}')
            for codigo, valor in respuesta.items():
                pregunta, _ = PreguntaAsistente.objects.get_or_create(
                    codigo=codigo,
                    defaults={'texto': 'Pregunta', 'orden': 1},
                )
                RespuestaLlamada.objects.create(llamada=llamada, pregunta=pregunta, texto_respuesta=valor)

            resumen = generar_resumen_llamada(llamada)

            assert ResumenLlamada.objects.filter(llamada=llamada).exists()
            if nivel == 'SEGURO':
                assert resumen.nivel_riesgo == 'BAJO'
                assert 'bajo' in resumen.texto_resumen.lower()
            elif nivel == 'INTERMEDIO':
                assert resumen.nivel_riesgo == 'MEDIO'
                assert 'medio' in resumen.texto_resumen.lower()
            else:
                assert resumen.nivel_riesgo == 'ALTO'
                assert 'PELIGRO' in resumen.texto_resumen.upper()


@pytest.mark.django_db
class TestCU08ConversarConAgente:
    def test_conversacion_completa_las_cinco_preguntas(self):
        llamada = Llamada.objects.create(numero_telefonico='5599887766')
        for orden, (codigo, texto) in enumerate(
            [
                ('nombre', 'Mi nombre es Ana López y necesito hablar con atención al cliente.'),
                ('institucion', 'Soy de un banco local.'),
                ('motivo', 'Quiero aclarar un cobro en mi cuenta.'),
                ('solicita_datos_personales', 'No, solo quiero información general.'),
                ('solicita_pago', 'No, no voy a transferir dinero ni pagar hoy mismo.'),
            ],
            start=1,
        ):
            PreguntaAsistente.objects.get_or_create(
                codigo=codigo,
                defaults={'texto': f'Pregunta {orden}', 'orden': orden, 'activa': True},
            )

        sesion = SesionConversacion.objects.create(llamada=llamada, estado='INICIADA')
        agente = AgenteVoz(sesion)

        for respuesta in [
            'Mi nombre es Ana López y necesito hablar con atención al cliente.',
            'Soy de un banco local.',
            'Quiero aclarar un cobro en mi cuenta.',
            'No, solo quiero información general.',
            'No, no voy a transferir dinero ni pagar hoy mismo.',
        ]:
            agente.procesar_respuesta(respuesta)

        sesion.refresh_from_db()
        assert sesion.estado == 'FINALIZADA'
        assert sesion.intervenciones.count() >= 6
        assert RespuestaLlamada.objects.filter(llamada=llamada).count() == 5
        assert TranscripcionLlamada.objects.filter(llamada=llamada).count() >= 5

    def test_agente_puede_repetir_una_pregunta(self):
        llamada = Llamada.objects.create(numero_telefonico='5511223344')
        for orden, codigo in enumerate(['nombre', 'institucion', 'motivo', 'solicita_datos_personales', 'solicita_pago'], start=1):
            PreguntaAsistente.objects.get_or_create(
                codigo=codigo,
                defaults={'texto': f'Pregunta {codigo}', 'orden': orden, 'activa': True},
            )

        sesion = SesionConversacion.objects.create(llamada=llamada, estado='INICIADA')
        agente = AgenteVoz(sesion)
        agente.iniciar()

        resultado = agente.procesar_respuesta('repita la pregunta')

        assert resultado['repetir_pregunta'] is True
        assert sesion.estado in {'ESPERANDO_RESPUESTA', 'INICIADA'}
        assert sesion.intervenciones.filter(tipo='PREGUNTA').count() >= 2


@pytest.mark.django_db
class TestCU09GenerarVozDeAgente:
    def test_generar_audio_del_agente_crea_archivo(self):
        audio = generar_audio('Hola. ¿Puede repetir su nombre?', idioma='es-MX', voz='es-ES-Standard-A')

        assert audio['estado'] == 'OK'
        assert audio['archivo']
        assert audio['ruta'].endswith('.wav')
        assert audio['ruta'] and os.path.exists(audio['ruta'])

    def test_generar_audio_rechaza_texto_vacio(self):
        audio = generar_audio('   ')

        assert audio['estado'] == 'ERROR'
        assert 'texto' in audio['error'].lower()


@pytest.mark.django_db
class TestCU10RealizarLlamada:
    def test_realizar_llamada_crea_registro_y_prepara_alerta(self):
        llamada = realizar_llamada('5512345678')

        assert llamada.pk is not None
        assert llamada.numero_telefonico == '5512345678'
        assert llamada.estado in {EstadoLlamada.PENDIENTE_DE_EVALUACION, EstadoLlamada.PERMITIDA}
        assert llamada.preparada_para_asistente_voz is True


@pytest.mark.django_db
class TestCU11MostrarAlertaRiesgo:
    def test_alerta_riesgo_incluye_resumen_y_nivel(self):
        llamada = Llamada.objects.create(numero_telefonico='5566778899')
        PreguntaAsistente.objects.get_or_create(
            codigo='nombre',
            defaults={'texto': '¿Cómo se identifica?', 'orden': 1, 'activa': True},
        )
        RespuestaLlamada.objects.create(
            llamada=llamada,
            pregunta=PreguntaAsistente.objects.get(codigo='nombre'),
            texto_respuesta='Pedro López',
        )

        alert = mostrar_alerta_riesgo(llamada)

        assert alert['llamada'] == llamada
        assert alert['nivel'] in {'BAJO', 'MEDIO', 'ALTO', 'SIN_EVALUAR'}
        assert 'texto_resumen' in alert


@pytest.mark.django_db
class TestCU12ContestarLlamadaEvaluada:
    def test_contestar_llamada_evaluada_la_permite_y_registra_decision(self):
        llamada = Llamada.objects.create(numero_telefonico='5588997744', estado=EstadoLlamada.PENDIENTE_DE_EVALUACION)

        llamada_actualizada = contestar_llamada_evaluada(llamada, motivo='Se acepta porque el contacto es confiable.')

        assert llamada_actualizada.estado == EstadoLlamada.PERMITIDA
        assert 'acepta' in llamada_actualizada.resultado_evaluacion.lower()


@pytest.mark.django_db
class TestCU13RechazarLlamadaEvaluada:
    def test_rechazar_llamada_evaluada_bloquea_el_contacto(self):
        llamada = Llamada.objects.create(numero_telefonico='5599001122', estado=EstadoLlamada.PENDIENTE_DE_EVALUACION)

        llamada_actualizada = rechazar_llamada_evaluada(llamada, motivo='Llamada con riesgo alto.')

        assert llamada_actualizada.estado == EstadoLlamada.RECHAZADA
        assert 'riesgo' in llamada_actualizada.resultado_evaluacion.lower()


@pytest.mark.django_db
class TestCU18ReproducirTextoAVoz:
    def test_reproduce_texto_importante_en_espanol(self):
        resultado = reproducir_texto_voz('El riesgo es alto. Por favor, atienda la alerta.')

        assert resultado['estado'] == 'OK'
        assert resultado['ruta']
        assert os.path.exists(resultado['ruta'])

    def test_no_generar_audio_si_el_texto_esta_vacio(self):
        resultado = reproducir_texto_voz('   ')

        assert resultado['estado'] == 'ERROR'
        assert 'texto' in resultado['error'].lower()


@pytest.mark.django_db
class TestCU19RegistrarContactoSeguro:
    def test_contacto_duplicado_para_el_mismo_usuario_no_se_guarda(self):
        usuario = User.objects.create_user(username='usuario_protegido', password='secure-pass-123')
        ContactoConfianza.objects.create(
            usuario_protegido=usuario,
            nombre='Marta López',
            numero_telefonico='5512345678',
            relacion='Hija',
            activo=True,
        )

        client = Client()
        response = client.post('/contactos/agregar/', {'nombre': 'Marta López', 'numero_telefonico': '5512345678', 'relacion': 'Hija', 'descripcion': 'Repetido', 'activo': 'on'})

        assert response.status_code == 200
        assert ContactoConfianza.objects.filter(usuario_protegido=usuario, numero_telefonico='5512345678').count() == 1

    def test_puede_registrar_contacto_con_relacion(self):
        usuario = User.objects.create_user(username='familiar2', password='secret123')

        contacto = ContactoConfianza.objects.create(
            usuario_protegido=usuario,
            nombre='Carlos Ruiz',
            numero_telefonico='5522334455',
            relacion='Hermano',
            descripcion='Contacto seguro',
            activo=True,
        )

        assert contacto.relacion == 'Hermano'
        assert contacto.usuario_protegido == usuario
