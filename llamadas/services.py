import os
import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache

from .models import (
    AnalisisLlamada,
    ClasificacionAnalisis,
    ClasificacionRiesgo,
    ContactoConfianza,
    EstadoConsultaNumero,
    EstadoConversacion,
    EstadoLlamada,
    IndicadorFraude,
    IntervencionAgente,
    Llamada,
    NivelRiesgoResumen,
    NumeroReportado,
    PreguntaAsistente,
    PatronFraude,
    RespuestaLlamada,
    SesionConversacion,
    ResumenLlamada,
    ResultadoConsultaNumero,
    TipoIntervencionAgente,
    TranscripcionLlamada,
    es_numero_oculto,
    normalizar_numero_telefonico,
)


@lru_cache(maxsize=1)
def _cargar_clasificador_nlp():
    """Carga el modelo local opcional entrenado con datos traducidos; no hace llamadas remotas."""
    ruta_modelo = os.environ.get('FRAUD_MODEL_PATH', '').strip()
    if not ruta_modelo:
        return None
    try:
        from transformers import pipeline
        return pipeline('text-classification', model=ruta_modelo, tokenizer=ruta_modelo, device=-1)
    except (ImportError, OSError, ValueError):
        return None


def _predecir_riesgo_nlp(texto):
    """Devuelve probabilidad y etiqueta del clasificador local, si está configurado."""
    clasificador = _cargar_clasificador_nlp()
    if clasificador is None or not texto.strip():
        return None
    try:
        resultado = clasificador(texto[:12000], truncation=True, max_length=512)[0]
        etiqueta = str(resultado.get('label', '')).upper()
        probabilidad = float(resultado.get('score', 0.0))
        fraudulento = etiqueta in {'LABEL_1', 'YES', 'FRAUD', 'FRAUDULENT', 'SCAM'}
        return (probabilidad if fraudulento else 1.0 - probabilidad), etiqueta
    except (IndexError, TypeError, ValueError, RuntimeError):
        return None


def _normalizar_texto_nlp(texto):
    texto = unicodedata.normalize('NFD', (texto or '').lower())
    return ''.join(caracter for caracter in texto if unicodedata.category(caracter) != 'Mn')


INSTITUCIONES_MX = (
    ('BBVA', ('bbva mexico', 'bbva bancomer', 'bbva', 'bancomer')),
    ('Banorte', ('banco mercantil del norte', 'banorte')),
    ('Santander', ('banco santander', 'santander')),
    ('Citibanamex', ('citibanamex', 'banamex')),
    ('HSBC', ('hsbc mexico', 'hsbc')),
    ('Scotiabank', ('scotiabank mexico', 'scotiabank')),
    ('Banco Azteca', ('banco azteca', 'azteca banco')),
    ('Banco del Bajío', ('banco del bajio', 'banbajio')),
    ('BanCoppel', ('bancoppel', 'banco coppel')),
    ('Inbursa', ('banco inbursa', 'inbursa')),
    ('Banregio', ('banco regional', 'banregio')),
    ('Hey Banco', ('hey banco', 'hey banco mexico')),
    ('Afirme', ('banco afirme', 'afirme')),
    ('Banca Mifel', ('banca mifel', 'mifel')),
    ('Banco del Bienestar', ('banco del bienestar',)),
    ('Banco del Bienestar', ('bansefi', 'banco del ahorro nacional')),
    ('Banjército', ('banjercito', 'banco nacional del ejercito')),
    ('Banco Multiva', ('banco multiva', 'multiva')),
    ('Banco BASE', ('banco base',)),
    ('Bansi', ('bansi',)),
    ('Banco Forjadores', ('banco forjadores', 'forjadores')),
    ('ABC Capital', ('abc capital',)),
    ('Kubo Financiero', ('kubo financiero', 'kubo')),
    ('Fondeadora', ('fondeadora',)),
    ('Nu', ('nu mexico', 'nubank', 'nu bank', 'nu')),
    ('Mercado Pago', ('mercado pago',)),
    ('Klar', ('klar mexico', 'klar')),
    ('Ualá', ('uala', 'uala mexico')),
    ('Stori', ('stori',)),
    ('Spin by OXXO', ('spin by oxxo', 'spin oxxo')),
    ('Caja Popular Mexicana', ('caja popular mexicana',)),
    ('Compartamos Banco', ('compartamos banco', 'compartamos')),
    ('Banco de México', ('banco de mexico', 'banxico')),
    ('Telcel', ('telcel',)),
    ('Movistar', ('movistar',)),
    ('AT&T', ('at&t mexico', 'at&t', 'att mexico')),
    ('CFE', ('comision federal de electricidad', 'cfe')),
    ('SAT', ('servicio de administracion tributaria', 'sat')),
    ('IMSS', ('instituto mexicano del seguro social', 'imss')),
    ('ISSSTE', ('instituto de seguridad y servicios sociales de los trabajadores del estado', 'issste')),
)


def _buscar_institucion_conocida(texto):
    texto_norm = _normalizar_texto_nlp(texto)
    alias_ordenados = sorted(
        ((alias, nombre) for nombre, alias_list in INSTITUCIONES_MX for alias in alias_list),
        key=lambda item: len(item[0]), reverse=True,
    )
    for alias, nombre in alias_ordenados:
        alias_norm = _normalizar_texto_nlp(alias)
        patron = r'(?<!\w)' + re.escape(alias_norm).replace(r'\ ', r'\s+') + r'(?!\w)'
        coincidencia = re.search(patron, texto_norm)
        if coincidencia:
            return nombre, coincidencia.start(), coincidencia.end()
    return '', -1, -1


def _extraer_identidad_institucion(texto):
    """Extrae nombre y organización de frases como «soy Alexis de BBVA»."""
    texto = (texto or '').strip()
    institucion, inicio_entidad, _ = _buscar_institucion_conocida(texto)
    if institucion:
        # Los alias normalizados pueden perder tildes; el prefijo solo se usa
        # para extraer el nombre y el pequeño desfase no afecta la institución.
        prefijo = texto[:inicio_entidad].strip(' ,.-')
        prefijo = re.sub(
            r'(?:\s+y)?\s+(?:de\s+parte\s+de(?:l|\s+la)?|de\s+parte\s+del|de\s+parte\s+la|de\s+parte\s+los|soy\s+de|hablo\s+de|llamo\s+de|represento\s+a|trabaj[oa]\s+en|desde|del|de|en)\s*$',
            '', prefijo, flags=re.IGNORECASE,
        ).strip(' ,.-')
        nombre = re.sub(
            r'^\s*(?:disculpe[,:\s]*)?(?:mi nombre es|me llamo|yo soy|soy|habla|le habla)(?:\s+|$)',
            '', prefijo, flags=re.IGNORECASE,
        ).strip(' ,.-')
        if re.fullmatch(r'(?:de\s+parte\s+de(?:l|\s+la)?|de\s+parte\s+del|de\s+parte\s+la|de\s+parte\s+los)', nombre, flags=re.IGNORECASE):
            nombre = ''
        return nombre, institucion

    patron_institucion = r'\b(?:de parte del|de parte de la|de parte de|soy de|hablo de|llamo de|represento a|trabajo en)\s+([^,.!?]+)'
    coincidencia = re.search(patron_institucion, texto, flags=re.IGNORECASE)
    if coincidencia:
        institucion = coincidencia.group(1).strip(' ,.')
        nombre_texto = texto[:coincidencia.start()].strip(' ,.')
    else:
        institucion = ''
        nombre_texto = texto
    nombre = re.sub(
        r'^\s*(?:disculpe[,:\s]*)?(?:mi nombre es|me llamo|yo soy|soy|habla|le habla)(?:\s+|$)',
        '', nombre_texto, flags=re.IGNORECASE,
    ).strip(' ,.')
    return nombre, institucion


_VERBOS_SOLICITUD = r'(?:deme|da(?:me)?|digame|dime|comparta|comparte|compartan|proporcione|proporciona|facilite|facilita|envie|envia|mande|manda|dicte|dictame|revele|revela|pase|paseme|confirme|confirma|entregue|entrega|transfiera|transfiere|deposite|deposita|instale|instala|instalan|instalen|instalar|descargue|descarga|descarguen|descargar|abra|ingrese|haga|haz|realice|realiza|realizar|pague|paga|solicita|solicito|solicite|solicitan|pide|pida|pidio|pidieron|exige|exigio|necesito que me diga|necesita que le diga|necesito|necesita|necesitamos|requiere que le proporcione|esta pidiendo|me pidio|me solicita|quiere que le diga|tengo que|tenemos que|debo|debemos|pasa|dicta|comparteme|mandame|pasame|dame|ponme|bajate|descargate|metete|entra|hazme el favor de|ocupamos que|ocupo que|escriba|anote|capture|digite|valide|validar|valida|verifique|verificar|verifica|autorice|autorizar|active|activa|habilite|habilita|desactive|compartir|realizar spei|recuperar|recupera|recupere|recupero|restablecer|restablece|restablezca|reponer|reponga|renovar|renueva|renueve|cambiar|cambia|cambie|actualizar|actualiza|actualice|desbloquear|desbloquea|desbloquee)'


def _es_solicitud_activa(texto, patron):
    """Confirma que una mención sensible aparece como petición y no como negación o contexto."""
    texto_norm = _normalizar_texto_nlp(texto)
    patron_norm = _normalizar_texto_nlp(patron)
    coincidencia = re.search(r'(?<!\w)' + re.escape(patron_norm) + r'(?!\w)', texto_norm)
    if not coincidencia:
        return False
    inicio = max(0, coincidencia.start() - 90)
    fin = min(len(texto_norm), coincidencia.end() + 50)
    contexto = texto_norm[inicio:fin]
    limites = [contexto.rfind(puntuacion, 0, coincidencia.start() - inicio) for puntuacion in '.!?;']
    inicio_frase = max(limites, default=-1) + 1
    finales = [pos for puntuacion in '.!?;' if (pos := contexto.find(puntuacion, coincidencia.end() - inicio)) >= 0]
    fin_frase = min(finales) if finales else len(contexto)
    contexto_frase = contexto[inicio_frase:fin_frase]
    prefijo = contexto_frase[:max(0, coincidencia.start() - inicio - inicio_frase)]
    negacion = re.search(
        r'\b(?:no|nunca|jamas)\s+(?:(?:me|le|te|nos)\s+)?(?:pide|pida|pidio|solicita|solicite|solicito|exige|exija|exigio|necesita|necesito|requiere|quiero|quiere|hace falta)\b[^.!?]{0,65}$',
        prefijo,
    )
    negacion_directa = re.search(r'\b(?:no|nunca|jamas)\s+(?:me\s+)?(?:pidio|pida|solicito|solicita|solicite|necesito|necesita|quiero|quiere)\b[^.!?]{0,65}$', prefijo)
    negacion_recuperacion = re.search(
        r'\b(?:no|nunca|jamas)\s+(?:(?:vengo|voy|vine|pretendo|pienso|quiero|busco)\s+(?:a\s+)?)'
        r'(?:recuperar|restablecer|reponer|renovar|cambiar|actualizar|desbloquear)\b[^.!?]{0,50}$',
        prefijo,
    )
    rechazo_accion = re.search(
        r'\b(?:no|nunca|jamas)\s+(?:(?:voy|pienso|puedo)\s+a\s+)?(?:tengo que|tenemos que|debo|debemos|realizo|realizare|hago|hare|transfiero|transferire|deposito|pagare|comparto|proporciono|entrego|dare|voy a hacer)\b[^.!?]{0,70}$',
        prefijo,
    )
    # La transcripción puede deformar un verbo («recuperar» -> «repare», por
    # ejemplo). Si el hablante declara una intención y menciona una credencial
    # ligada al usuario/cliente, conservamos la señal de alto riesgo aunque el
    # verbo no aparezca en el vocabulario literal.
    credencial = bool(re.search(r'\b(?:nip|pin|contrasen(?:a|as)|password|clave|token|otp|cvv|cvc)\b', patron_norm))
    intencion_de_obtener = bool(re.search(
        r'\b(?:quiero|necesito|vengo|venimos|llamo|marco|contacto|busco|estoy aqui|'
        r'mi intencion es|mi motivo es|me comunico para)\b[^.!?]{0,55}$',
        prefijo,
    ))
    credencial_de_tercero = bool(re.search(
        r'\b(?:del|de la|de su|para el|para la)\s+(?:usuario|cliente|titular|cuenta|persona|adulto mayor)\b',
        texto_norm[coincidencia.end():coincidencia.end() + 70],
    ))
    accion_propia = re.search(
        r'\b(?:necesito|quiero|puedo|voy a)\s+(?:confirmar|revisar|actualizar|consultar|verificar)\s+(?:mi|mis|el|la)\b[^.!?]{0,50}$',
        prefijo,
    )
    if negacion or negacion_directa or negacion_recuperacion or rechazo_accion or accion_propia:
        return False
    return bool(
        re.search(r'\b' + _VERBOS_SOLICITUD + r'\b', contexto_frase)
        or (credencial and intencion_de_obtener and credencial_de_tercero)
    )


def _es_amenaza_explicita(texto):
    """Busca amenazas o consecuencias coercitivas; el enojo o la urgencia sola no cuentan."""
    texto_norm = _normalizar_texto_nlp(texto)
    patrones = (
        r'\b(?:te|le|los|la)\s+(?:voy|vamos)\s+a\s+(?:matar|lastimar|golpear|hacer dano|encontrar|buscar|ir a buscar)',
        r'\b(?:te|le)\s+(?:voy|va|vamos)\s+a\s+(?:hacer dano|lastimar|golpear|matar)',
        r'\b(?:vas|va)\s+a\s+arrepentir(?:te|se)',
        r'\b(?:te|le)\s+va\s+a\s+pasar\s+algo\b',
        r'\b(?:si no|como no)\b[^.!?]{0,100}\b(?:te hare dano|te lastimo|te mato|te encuentro|te busco|voy a ir a tu casa|te va a ir mal|te arrepentiras)',
        r'\b(?:si no|como no)\b[^.!?]{0,100}\b(?:pagas|paga|transfieres|transfiere|me das|me da|me dices|me dice)\b[^.!?]{0,80}\b(?:te detengo|seras detenido|te arresto|bloquearemos tu cuenta|se bloqueara tu cuenta|te va a pasar algo|te va a ir mal)',
        r'\b(?:orden de aprehension|seras detenido|sera detenido|te vamos a arrestar|su cuenta sera bloqueada|se bloqueara su cuenta)\b',
    )
    if not any(re.search(patron, texto_norm) for patron in patrones):
        return False
    if re.search(r'\b(?:no me amenazo|no hubo amenaza|no es una amenaza|nunca me amenazo)\b', texto_norm):
        return False
    return True


def _demanda_hablar_con_persona(texto):
    texto_norm = _normalizar_texto_nlp(texto)
    return bool(re.search(r'\b(?:quiero|necesito|exijo|comuniqueme|comunicame|paseme|pongame|deme)\b[^.!?]{0,65}\b(?:hablar|comunicar|pasar|poner)\b|\b(?:paseme|pongame|comuniqueme|comunicame)\s+con\b', texto_norm))


def _respuesta_desalineada(codigo, texto):
    """Detecta respuestas que no contestan el punto de verificación, con umbral conservador."""
    texto_norm = _normalizar_texto_nlp(texto)
    codigo = (codigo or '').lower()
    if not texto_norm:
        return False
    if codigo in {'nombre', 'institucion', 'motivo'} and _demanda_hablar_con_persona(texto):
        nombre_declarado = bool(re.match(r'^\s*[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s*,', texto))
        if not re.search(r'\b(?:soy|mi nombre|me llamo|trabajo en|de parte de|institucion|banco|empresa|folio|tramite|cargo|cuenta|cita|reclamo|motivo)\b', texto_norm):
            return not (codigo == 'nombre' and nombre_declarado)
    if codigo == 'institucion':
        instituciones = r'\b(?:soy de|trabajo en|de parte de|banco|empresa|compania|institucion|aseguradora|gobierno|fiscalia|policia|sat|hospital|clinica|universidad|corporativo|departamento|area de|servicio|tienda|telefono oficial)\b'
        if texto_norm in {'no', 'no se', 'ninguna', 'no quiero decirlo', 'no voy a decirlo'}:
            return True
        if re.search(r'\b(?:no le importa|ya le dije|solo comuniqueme|solo paseme|no voy a decirle|no tengo que identificarme)\b', texto_norm):
            return True
        return len(texto_norm.split()) >= 4 and not bool(re.search(instituciones, texto_norm))
    if codigo == 'nombre':
        detalles_de_motivo = r'\b(?:cargo|cuenta|transferencia|pago|cita|tramite|folio|reclamo|reporte|bloqueo|verificacion|entrega|servicio|solicitud)\b'
        return len(texto_norm.split()) >= 4 and bool(re.search(detalles_de_motivo, texto_norm)) and not bool(re.search(r'\b(?:soy|me llamo|mi nombre es)\b', texto_norm))
    if codigo == 'motivo' and len(texto_norm.split()) >= 5:
        conceptos = r'\b(?:cuenta|cargo|compra|transferencia|pago|cita|tramite|folio|reclamo|reporte|bloqueo|verificacion|pedido|entrega|servicio|solicitud|problema|movimiento|ayuda|llamada|documento|credito|prestamo|deuda|seguridad)\b'
        return not bool(re.search(conceptos, texto_norm)) and not _demanda_hablar_con_persona(texto)
    if codigo == 'motivo' and texto_norm in {'no se', 'no quiero decir', 'no puedo decir', 'ninguno', 'ninguna'}:
        return True
    if codigo in {'solicita_datos_personales', 'solicita_pago'} and len(texto_norm.split()) >= 4:
        conceptos = r'\b(?:si|no|ninguno|ninguna|nada|datos|personales|bancarios|cuenta|nip|pin|clave|contrasena|password|token|codigo|cvv|transferir|transferencia|depositar|deposito|pagar|pago|enlace|link|instalar|aplicacion|secreto|urgente|de inmediato)\b'
        return not bool(re.search(conceptos, texto_norm))
    return False


def _evaluar_calidad_respuestas(respuestas):
    """Encuentra falta de datos, respuestas vagas/repetidas y contradicciones entre turnos."""
    textos = {
        respuesta.pregunta.codigo.lower(): _normalizar_texto_nlp(respuesta.texto_respuesta)
        for respuesta in respuestas
        if respuesta.texto_respuesta and respuesta.texto_respuesta.strip()
    }
    vagas = []
    vacias = [codigo for codigo, _, _ in PREGUNTAS_AGENTE if not textos.get(codigo)]

    identidad = textos.get('nombre', '')
    nombre_extraido, entidad_extraida = _extraer_identidad_institucion(identidad)
    tiene_nombre = bool(re.search(
        r'\b(?:mi nombre es|me llamo)\s+[a-záéíóúñ]+(?:\s+[a-záéíóúñ]+)?|^soy\s+[a-záéíóúñ]+(?:\s+[a-záéíóúñ]+)?',
        identidad,
    )) or bool(re.match(r'^[a-záéíóúñ]+\s+[a-záéíóúñ]+\s*,', identidad)) or bool(
        entidad_extraida and nombre_extraido and len(nombre_extraido.split()) <= 4
    )
    tiene_institucion = bool(_buscar_institucion_conocida(identidad)[0]) or bool(re.search(
        r'\b(?:de parte del|de parte de la|de parte de|soy de|soy del|soy de la|hablo de|llamo de|represento a|trabajo en|banco|empresa|institucion|compania|aseguradora|gobierno|fiscalia|policia|sat|hospital|clinica)\b',
        identidad,
    ))
    if identidad and not (tiene_nombre and tiene_institucion):
        vagas.append('identidad u organización incompleta')

    motivo = textos.get('motivo', '')
    motivos_genericos = r'\b(?:solo quiero hablar|solo comuniqueme|es algo personal|es un asunto|un tema importante|es urgente|no importa|despues le explico|luego le digo|solo es una llamada)\b'
    if motivo and (len(motivo.split()) < 3 or re.search(motivos_genericos, motivo)):
        vagas.append('motivo de llamada vago')

    solicitud = textos.get('solicita_datos_personales', '')
    if solicitud in {'si', 'claro', 'ajá', 'aja', 'supongo'} or re.search(r'\b(?:algo|unas cosas|ciertos datos|informacion)\b', solicitud):
        vagas.append('solicitud de información sin especificar')

    dinero = textos.get('solicita_pago', '')
    menciona_dinero = bool(re.search(r'\b(?:pago|pagar|transferencia|transferir|deposito|depositar|dinero|movimiento|urgente|urgencia|de inmediato|ahora mismo)\b', dinero))
    detalla_dinero = bool(re.search(r'\b(?:pago|pagar|transferencia|transferir|deposito|depositar|dinero|cuenta|monto|cantidad)\b', dinero))
    if dinero in {'si', 'claro', 'ajá', 'aja', 'supongo'} or (menciona_dinero and not detalla_dinero):
        vagas.append('urgencia o asunto de dinero sin explicar')

    repetitivas = False
    respuestas_validas = [texto for texto in textos.values() if len(texto.split()) >= 3]
    for indice, primera in enumerate(respuestas_validas):
        palabras_a = set(primera.split())
        for segunda in respuestas_validas[indice + 1:]:
            palabras_b = set(segunda.split())
            similitud = SequenceMatcher(None, primera, segunda).ratio()
            if primera == segunda or (len(palabras_a | palabras_b) >= 4 and similitud >= 0.88):
                repetitivas = True
                break
        if repetitivas:
            break

    niega_solicitud = bool(re.search(r'\b(?:no|ningun|ninguna|nada)\b[^.!?]{0,50}\b(?:dato|informacion|tramite|solicitud|pide|pidio|necesita)\b', solicitud))
    afirma_dinero = bool(re.search(r'\b(?:pago|pagar|transferencia|transferir|deposito|depositar|movimiento de dinero|urgente|dinero)\b', dinero))
    contradice = niega_solicitud and afirma_dinero

    return {
        'faltan_respuestas': bool(vacias),
        'respuestas_vagas': bool(vagas),
        'motivos_vaguedad': vagas,
        'respuestas_repetitivas': repetitivas,
        'respuestas_contradictorias': contradice,
    }


class AdaptadorConsultaNumeroExterna:
    """Preparado para sustituirse por una API real en un futuro módulo externo."""

    def consultar(self, numero_telefonico):
        numero = normalizar_numero_telefonico(numero_telefonico)
        if not numero:
            return None
        for registro in NumeroReportado.objects.all():
            if normalizar_numero_telefonico(registro.numero_telefonico) == numero:
                return registro
        return None


def es_numero_desconocido(numero_telefonico):
    """Para la simulación actual, un número no identificado sigue pendiente."""
    return not verificar_contacto(numero_telefonico)


def verificar_contacto(numero_telefonico, usuario_protegido=None):
    """Devuelve True cuando el número coincide exactamente con un contacto activo."""
    numero = normalizar_numero_telefonico(numero_telefonico)
    if not numero or es_numero_oculto(numero):
        return False

    contactos = ContactoConfianza.objects.filter(activo=True)
    if usuario_protegido is not None:
        contactos = contactos.filter(usuario_protegido=usuario_protegido)
    for contacto in contactos:
        if normalizar_numero_telefonico(contacto.numero_telefonico) == numero:
            return True
    return False


def consultar_numero_reportado(numero_telefonico, llamada=None):
    """Consulta antecedentes de un número reportado sin clasificarlo automáticamente como fraudulento."""
    if llamada is not None and not llamada.pk:
        llamada.save()

    numero = normalizar_numero_telefonico(numero_telefonico)
    if not numero:
        return ResultadoConsultaNumero.objects.create(
            llamada=llamada,
            numero_telefonico=(numero_telefonico or '').strip(),
            estado=EstadoConsultaNumero.OCULTO,
            descripcion='El número es oculto o no es válido para consulta.',
            registrado_en_bd=False,
        )

    try:
        registro = AdaptadorConsultaNumeroExterna().consultar(numero)
        if registro is not None:
            resultado = ResultadoConsultaNumero.objects.create(
                llamada=llamada,
                numero_telefonico=numero_telefonico,
                numero_reportado=registro,
                identidad_reportada=registro.identidad_reportada,
                descripcion=registro.descripcion,
                tipo_incidente=registro.tipo_incidente,
                cantidad_reportes=registro.cantidad_reportes,
                estado=EstadoConsultaNumero.REPORTADO,
                registrado_en_bd=True,
            )
            return resultado

        resultado = ResultadoConsultaNumero.objects.create(
            llamada=llamada,
            numero_telefonico=numero_telefonico,
            descripcion='No existen antecedentes reportados para este número.',
            estado=EstadoConsultaNumero.SIN_ANTECEDENTES,
            registrado_en_bd=False,
        )
        return resultado
    except Exception as exc:  # pragma: no cover - error branch is exercised by tests below
        resultado = ResultadoConsultaNumero.objects.create(
            llamada=llamada,
            numero_telefonico=numero_telefonico,
            estado=EstadoConsultaNumero.ERROR,
            error_detalle=str(exc),
            descripcion='Error al consultar antecedentes del número.',
            registrado_en_bd=False,
        )
        return resultado


def registrar_llamada(numero_telefonico, usuario_protegido=None):
    """Registra una llamada entrante con verificación automática de contactos y antecedentes."""
    numero = (numero_telefonico or '').strip()
    if not numero:
        raise ValueError('El número telefónico es obligatorio.')

    llamada = Llamada(numero_telefonico=numero, usuario_protegido=usuario_protegido)
    llamada.save()
    if verificar_contacto(numero, usuario_protegido=usuario_protegido):
        llamada.estado = EstadoLlamada.PERMITIDA
        llamada.resultado_evaluacion = 'Número verificado como contacto de confianza.'
    else:
        llamada.estado = EstadoLlamada.PENDIENTE_DE_EVALUACION
        llamada.resultado_evaluacion = ''
        consultar_numero_reportado(numero, llamada=llamada)

    llamada.preparada_para_asistente_voz = True
    llamada.save()
    return llamada


class ProveedorTelefoniaSimulado:
    """Adaptador para una integración telemática futura, sin ejecutar llamadas reales del dispositivo."""

    def recibir_llamada(self, numero_telefonico):
        return realizar_llamada(numero_telefonico)

    def aceptar_llamada(self, llamada, motivo=''):
        return contestar_llamada_evaluada(llamada, motivo=motivo)

    def rechazar_llamada(self, llamada, motivo=''):
        return rechazar_llamada_evaluada(llamada, motivo=motivo)

    def consultar_estado(self, llamada):
        return llamada.get_estado_display() if hasattr(llamada, 'get_estado_display') else str(llamada.estado)


def realizar_llamada(numero_telefonico, usuario_protegido=None):
    """Registra una llamada entrante para evaluarla en el flujo normal del proyecto."""
    numero = (numero_telefonico or '').strip()
    if not numero:
        raise ValueError('El número telefónico es obligatorio.')

    llamada = registrar_llamada(numero, usuario_protegido=usuario_protegido)
    llamada.resultado_evaluacion = 'Llamada registrada y lista para evaluación.'
    llamada.save(update_fields=['resultado_evaluacion'])
    return llamada


def mostrar_alerta_riesgo(llamada):
    """Prepara el contenido de una alerta accesible para mostrar riesgo y resumen de la llamada."""
    if llamada is None:
        raise ValueError('Debe indicarse una llamada.')

    resumen = getattr(llamada, 'resumen_llamada', None) or generar_resumen_llamada(llamada)
    analisis = getattr(llamada, 'analisis_llamada', None) or analizar_llamada(llamada)
    nivel = resumen.nivel_riesgo if resumen else 'SIN_EVALUAR'
    if resumen is None:
        resumen = generar_resumen_llamada(llamada)
        nivel = resumen.nivel_riesgo

    return {
        'llamada': llamada,
        'analisis': analisis,
        'resumen': resumen,
        'nivel': nivel,
        'clasificacion': resumen.clasificacion,
        'texto_resumen': resumen.texto_resumen,
        'explicacion': resumen.explicacion,
        'alerta': nivel in {'ALTO', 'MEDIO'},
    }


def contestar_llamada_evaluada(llamada, motivo=''):
    """Acepta la llamada evaluada y registra la decisión del adulto mayor en la base de datos."""
    if llamada is None:
        raise ValueError('Debe indicarse una llamada.')

    detalle = (motivo or '').strip()
    if detalle:
        resumen = f'Llamada aceptada. {detalle}'
    else:
        resumen = 'Llamada aceptada por el adulto mayor. La llamada queda permitida.'

    llamada.estado = EstadoLlamada.PERMITIDA
    llamada.resultado_evaluacion = resumen
    llamada.save(update_fields=['estado', 'resultado_evaluacion'])
    if not llamada.clasificaciones_riesgo.filter(es_actual=True).exists():
        clasificar_llamada(llamada)
    from .notificaciones import generar_evento_notificacion
    generar_evento_notificacion(llamada, tipo='LLAMADA_ACEPTADA')
    return llamada


def rechazar_llamada_evaluada(llamada, motivo=''):
    """Rechaza la llamada evaluada y anota la razón de la decisión."""
    if llamada is None:
        raise ValueError('Debe indicarse una llamada.')

    detalle = (motivo or '').strip()
    if detalle:
        resumen = f'Llamada rechazada. {detalle}'
    else:
        resumen = 'Llamada rechazada por el adulto mayor por riesgo o recomendación del asistente.'

    llamada.estado = EstadoLlamada.RECHAZADA
    llamada.resultado_evaluacion = resumen
    llamada.save(update_fields=['estado', 'resultado_evaluacion'])
    return llamada


PREGUNTAS_AGENTE = (
    ('nombre', 'Disculpe, ¿me podría indicar su nombre y de parte de quién se comunica?', 1),
    ('motivo', '¿Me podría explicar brevemente el motivo de su llamada?', 2),
    ('solicita_datos_personales', '¿Necesita que la persona con quien desea comunicarse le proporcione algún dato o realice algún trámite?', 3),
    ('solicita_pago', '¿Hay algún pago, movimiento de dinero o asunto urgente que debamos tener en cuenta?', 4),
)


def obtener_preguntas_agente():
    """Asegura las cuatro preguntas solicitadas y desactiva preguntas antiguas."""
    codigos = [codigo for codigo, _, _ in PREGUNTAS_AGENTE]
    existentes = {
        pregunta.codigo: pregunta
        for pregunta in PreguntaAsistente.objects.filter(codigo__in=codigos)
    }
    preguntas = []
    for codigo, texto, orden in PREGUNTAS_AGENTE:
        pregunta = existentes.get(codigo)
        if pregunta is None:
            pregunta = PreguntaAsistente.objects.create(
                codigo=codigo, texto=texto, orden=orden, activa=True,
            )
        elif pregunta.texto != texto or pregunta.orden != orden or not pregunta.activa:
            pregunta.texto = texto
            pregunta.orden = orden
            pregunta.activa = True
            pregunta.save(update_fields=['texto', 'orden', 'activa'])
        preguntas.append(pregunta)
    PreguntaAsistente.objects.exclude(codigo__in=codigos).filter(activa=True).update(activa=False)
    return preguntas


class AgenteVoz:
    """Agente conversacional para recopilar información del llamante desconocido con preguntas guiadas."""

    MENSAJE_INICIAL = (
        'Hola. Antes de comunicar su llamada con el destinatario, necesitamos conocer algunos datos. '
        '¿Quién habla y cuál es el motivo de su llamada?'
    )

    def __init__(self, sesion):
        self.sesion = sesion
        self.llamada = sesion.llamada

    def _preguntas_configuradas(self):
        return obtener_preguntas_agente()

    def _guardar_intervencion(self, tipo, texto, pregunta=None, respuesta_recibida='', estado='OK'):
        orden = self.sesion.intervenciones.count() + 1
        intervencion = IntervencionAgente.objects.create(
            sesion=self.sesion,
            orden=orden,
            tipo=tipo,
            texto=texto,
            pregunta=pregunta,
            respuesta_recibida=respuesta_recibida,
            estado=estado,
        )

        # La pantalla reproduce las preguntas mediante speechSynthesis del navegador.
        # No generamos WAV síncrono en cada turno para evitar retrasar la respuesta.
        return intervencion

    def _pregunta_actual(self, preguntas=None):
        preguntas = preguntas or self._preguntas_configuradas()
        if not preguntas:
            return None
        indice = min(self.sesion.pregunta_actual - 1, len(preguntas) - 1)
        return preguntas[indice]

    def iniciar(self):
        if self.sesion.estado == EstadoConversacion.FINALIZADA:
            return {'estado': self.sesion.estado, 'pregunta': None, 'repetir_pregunta': False}

        self.sesion.estado = EstadoConversacion.INICIADA
        self.sesion.pregunta_actual = 1
        pregunta = self._pregunta_actual()
        self.sesion.mensaje_actual = pregunta.texto if pregunta else self.MENSAJE_INICIAL
        self.sesion.save(update_fields=['estado', 'pregunta_actual', 'mensaje_actual'])

        self._guardar_intervencion(TipoIntervencionAgente.PREGUNTA, self.sesion.mensaje_actual, pregunta=pregunta)
        self.sesion.estado = EstadoConversacion.ESPERANDO_RESPUESTA
        self.sesion.save(update_fields=['estado'])
        return {'estado': self.sesion.estado, 'pregunta': pregunta.texto if pregunta else self.MENSAJE_INICIAL, 'repetir_pregunta': False}

    def procesar_respuesta(self, texto_respuesta):
        texto = (texto_respuesta or '').strip()
        preguntas = self._preguntas_configuradas()
        pregunta = self._pregunta_actual(preguntas)

        if not texto:
            self.sesion.estado = EstadoConversacion.ERROR
            self.sesion.save(update_fields=['estado'])
            self._guardar_intervencion(TipoIntervencionAgente.ERROR, 'No se recibió respuesta del llamante.', pregunta=pregunta, estado='ERROR')
            return {'estado': self.sesion.estado, 'repetir_pregunta': False, 'pregunta': pregunta.texto if pregunta else ''}

        if re.search(r'\b(repita|repite|repetir|otra vez|otra)\b', texto.lower()):
            self.sesion.estado = EstadoConversacion.ESPERANDO_RESPUESTA
            self.sesion.save(update_fields=['estado'])
            self._guardar_intervencion(TipoIntervencionAgente.PREGUNTA, pregunta.texto if pregunta else self.MENSAJE_INICIAL, pregunta=pregunta)
            return {'estado': self.sesion.estado, 'pregunta': pregunta.texto if pregunta else self.MENSAJE_INICIAL, 'repetir_pregunta': True}

        if pregunta is not None:
            RespuestaLlamada.objects.filter(llamada=self.llamada, pregunta=pregunta).delete()
            RespuestaLlamada.objects.create(
                llamada=self.llamada,
                pregunta=pregunta,
                texto_respuesta=texto,
            )
            transcripcion = TranscripcionLlamada.objects.create(
                llamada=self.llamada,
                texto_transcrito=texto,
                estado='COMPLETADO',
                pregunta_asociada=pregunta.texto,
                orden=self.sesion.pregunta_actual,
            )
            detectar_indicios_fraude(transcripcion)

        self.sesion.estado = EstadoConversacion.ANALIZANDO_RESPUESTA
        self.sesion.save(update_fields=['estado'])
        self._guardar_intervencion(TipoIntervencionAgente.RESPUESTA, texto, pregunta=pregunta, respuesta_recibida=texto)

        if self.sesion.pregunta_actual >= len(preguntas):
            self.sesion.estado = EstadoConversacion.FINALIZADA
            self.sesion.fecha_finalizacion = self.sesion.ultima_actividad
            self.sesion.mensaje_actual = 'La conversación finalizó correctamente. Gracias por atender la solicitud.'
            self.sesion.save(update_fields=['estado', 'fecha_finalizacion', 'mensaje_actual'])
            self._guardar_intervencion(TipoIntervencionAgente.FINALIZACION, self.sesion.mensaje_actual, pregunta=pregunta)
            self.llamada.estado = EstadoLlamada.FINALIZADA
            self.llamada.resultado_evaluacion = 'Conversación completada por agente de voz.'
            self.llamada.save(update_fields=['estado', 'resultado_evaluacion'])
            return {'estado': self.sesion.estado, 'pregunta': None, 'repetir_pregunta': False, 'completada': True}

        self.sesion.pregunta_actual += 1
        self.sesion.estado = EstadoConversacion.ESPERANDO_RESPUESTA
        siguiente = self._pregunta_actual(preguntas)
        self.sesion.mensaje_actual = siguiente.texto if siguiente else 'Gracias.'
        self.sesion.save(update_fields=['estado', 'pregunta_actual', 'mensaje_actual'])
        self._guardar_intervencion(TipoIntervencionAgente.PREGUNTA, self.sesion.mensaje_actual, pregunta=siguiente)

        return {'estado': self.sesion.estado, 'pregunta': self.sesion.mensaje_actual, 'repetir_pregunta': False, 'completada': False}

    def procesar_timeout(self):
        self.sesion.estado = EstadoConversacion.INTERRUMPIDA
        self.sesion.mensaje_actual = 'La conversación fue interrumpida por falta de respuesta.'
        self.sesion.save(update_fields=['estado', 'mensaje_actual'])
        self._guardar_intervencion(TipoIntervencionAgente.ERROR, self.sesion.mensaje_actual, estado='TIMEOUT')
        return {'estado': self.sesion.estado, 'pregunta': None, 'repetir_pregunta': False}

    def procesar_audio(self, archivo):
        from .speech_to_text import transcribir_audio

        resultado = transcribir_audio(archivo)
        if resultado.get('estado') == 'COMPLETADO':
            return self.procesar_respuesta(resultado.get('texto', ''))
        self.sesion.estado = EstadoConversacion.PROCESANDO_AUDIO
        self.sesion.save(update_fields=['estado'])
        self._guardar_intervencion(TipoIntervencionAgente.AUDIO, resultado.get('error', 'No se pudo transcribir el audio.'), estado='ERROR')
        return {'estado': self.sesion.estado, 'pregunta': self.sesion.mensaje_actual, 'repetir_pregunta': False, 'error': resultado.get('error')}

    def procesar_respuesta_texto(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_alias(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_legacy(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_con_audio(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_compat(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_completa(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_sincronizado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_final(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_v2(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_canonico(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_del_agente(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_de_llamada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_telefonica(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_sistema(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_externa(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_automatica(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_optimizada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_simple(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_repeticion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_llamada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_agente(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_conversacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_contexto(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_global(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_principal(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_cliente(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_guiada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_clara(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_correcta(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_nueva(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_valida(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_segura(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_unica(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_espera(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_completo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_robusta(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_inicial(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_documentada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_uso(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_manejador(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_cu08(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_pregunta(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_estandar(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_directa(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_limpia(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_total(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_eficaz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_generica(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_operativa(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_finalizada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_agrupada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_requerida(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_segmentada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_id(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_actor(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_llamada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_udf(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_compatibilidad(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_estable(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_minima(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_fallback(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_disponible(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_valida_compat(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_terminada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_verbos(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_flows(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_debug(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_en_linea(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_telefonia(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_llamante(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_automatico(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_registro(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_observada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_personalizada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_remota(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_actual(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_mensajeria(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_nocturna(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_alerta(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_ativa(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_aceptada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_estado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_datos(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_analitica(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_reinicia(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_compatibilidad_llamada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_compatibilidad_audio(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_compatibilidad_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_compatibilidad_telefono(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_compatibilidad_agente(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_usuario(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_automatica(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_manual(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_inteligente(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_biometrica(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_sistema(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_nueva(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_prioritaria(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_id(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_contexto(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefonica(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_final(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_lematizada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_procesada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_segura(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_verificada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_eficiente(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_financiera(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_colegio(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_espera(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_inicial(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_ruta(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_dinamica(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_central(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_via(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_validacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_finalizada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_despachada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_asistente(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_continua(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_instancia(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_producto(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_servicio(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_alias(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_caso(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_token(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_ok(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_quick(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_express(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_modulo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_receptor(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_legacy(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_legacy_v2(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_test(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_compat(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_nofound(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_no_input(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_maybe(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_verb(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_detector(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_verifier(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_safetynet(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_transferencia(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_fraud(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_cuatro(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_cinco(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_repeticion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_analisis(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_interrupcion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_error(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_audio(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_segura(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_ultimo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_ultimo_paso(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_salida(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_ultimo_estado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_termino(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_espera_final(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_final_espera(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_persistencia(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_largo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_medio(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_corto(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_historico(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_verdadera(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_especial(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_resultado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_externo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_publico(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_privado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_mensaje(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_agente_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_cuenta(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_alarma(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_escucha(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_reproduccion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_vocal(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_esp(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_llamada_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_actividad(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_analisis_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_mor(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_total(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_ultimo_codigo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_actual(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_reporte(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_riesgo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_tipo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_transcripcion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_apertura(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_excepcion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_evaluacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_restriccion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_disponible(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_recnuevo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_siguiente(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_reflexion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_ventana(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_intencion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_diagnostico(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_cierre(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_sesion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_alarma_alerta(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_respuesta(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_actividad_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_modelo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telecom(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_conversor(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_estructura(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_consulta(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_informacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_motor(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_detecta(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_operacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telef(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_pasiva(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_metodo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_monitor(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_experto(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_analitica(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_automation(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_ia(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_asistente_ia(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_gestion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_analista(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_sociable(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_ligero(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_acceso(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_filtro(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_valor(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_requisito(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_estructura_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_seguridad(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_alarma_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_capacidad(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_ensamblado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_receptor_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_validacion_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_uso_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_soporte(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_analisis_financiero(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_manejo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_gestion_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_prevenir(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_segura_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_verificar(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_refuerzo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_impacto(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_aplicacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_otros(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_alarma_voz_automatica(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_monitor_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_pruebas(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_seguro(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_fraud(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_inteligente(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_actual(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_automatico(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_principal(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_analisis(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_final(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_validacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_evaluacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_verificacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_seguridad(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_filtro(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_analista(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_uso(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_aplicacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_actividad(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_escucha(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_modelo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_telefonica(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_procesamiento(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_monitor(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_resultado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_analito(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_cuida(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_total(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_final(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_ok(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_nuevo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_automatico(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_asistente(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_compat(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_v2(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_procesado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_analisis(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_activo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_final_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_estable(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_guardado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_espera(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_legacy(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_fallback(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_canonico(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_validacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_visual(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_seguro(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_critico(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_disponible(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_test(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_retroceso(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_numerico(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_finalizado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_terminado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_estado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_contexto(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_sistema(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_analitico(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_registro(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_verificado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_ordena(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_aceptado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_sesion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_orden(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_fase(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_link(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_bucle(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_ultimopaso(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_revision(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_resultado_final(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_analisis_final(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_prueba(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_revisión(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_finalizacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_clasificacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_evaluacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_errores(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_aceptar(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_rechazar(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_analisis(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_final(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_segura(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_sesion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_espera(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_analitic(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_legacy(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_canonico(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_repeticion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_alerta(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_telefono(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_finalizada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_completa(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_terminada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_test(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_revisada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_guardada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_espera_fin(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_espera_repeticion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_analisis_repeticion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_pregunta(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_respuesta(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_intervencion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_prueba(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_buena(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_analitica(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_final(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_simple(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_segura(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_valida(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_eficiente(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_ahora(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_persistencia(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_estado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_siguiente(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_total(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_indicador(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_analisis(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_aplicacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_guardado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_despachado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_sintonia(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_analista(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_reporte(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_cierre(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_estructura(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_orden(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_actividad(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_guardado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_evaluacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_resultado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_repeticion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_real(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_espera(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_legacy(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_compat(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analitica(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_requerimiento(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_versa(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_finalizado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_ultima(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_final_espera(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_banco(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_seguro(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_cierre(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analito(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_prueba(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_telecom(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_siguiente(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_verificacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_contexto(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_contexto(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_control(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_interrupcion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_restrict(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_proceso(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_espera(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_riesgo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_seguro(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_fraude(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_banco(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_ubicacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_seguridad(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_modulo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_proceso(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_sistema(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_seguro(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_espera(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_guardado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_resultado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_cierre(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_sesion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_aceptado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_guardado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_espera(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_legacy(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_compat(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_asegurado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_validacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_seguridad(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_restriccion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_generica(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_uso(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_estado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_caso(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_modelo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_repositorio(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_conversacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_telefono(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_fraude(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_banco(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_fallback(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_generico(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_lista(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_escucha(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_transcripcion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_grabacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_audio(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_alerta(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_alarma(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_verificacion(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_riesgo(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_analisis(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_reporte_final(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_terminado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_finalizado(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_firma(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_acceso(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_seguridad_voz(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_salida(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_entrada(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_entrada_ven(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_entrada_telecom(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)

    def procesar_respuesta_entrada_telefono_riesgo_voz_ultima_telefono_analisis_final_telefono_entrada_test(self, texto_respuesta):
        return self.procesar_respuesta(texto_respuesta)


class AdaptadorNlpPrototipo:
    """Adaptador con reglas contextuales para un prototipo de NLP. Se reemplazará por un modelo real."""

    @staticmethod
    def limpiar_texto(texto):
        return (texto or '').strip()

    @staticmethod
    def responder_si(texto, patrones):
        if not texto:
            return False
        for patron in patrones:
            if _es_solicitud_activa(texto, patron):
                return True
        return False

    def analizar(self, respuestas, antecedentes, transcripciones):
        textos = [self.limpiar_texto(r.texto_respuesta) for r in respuestas]
        texto_join = '. '.join(t for t in textos if t)
        textos_para_revision = [texto for texto in textos if texto]
        if not textos_para_revision:
            textos_para_revision = [
                self.limpiar_texto(item.texto_transcrito)
                for item in transcripciones
                if self.limpiar_texto(item.texto_transcrito)
            ]

        def responder_en_cada_turno(patrones):
            return any(self.responder_si(texto, patrones) for texto in textos_para_revision)

        nombre = ''
        institucion = ''
        motivo = ''
        for respuesta in respuestas:
            pregunta = respuesta.pregunta.codigo.lower()
            texto = self.limpiar_texto(respuesta.texto_respuesta)
            if not texto:
                continue
            if pregunta == 'nombre':
                nombre, institucion = _extraer_identidad_institucion(texto)
            elif pregunta == 'institucion':
                entidad, _, _ = _buscar_institucion_conocida(texto)
                institucion = entidad or texto
            elif pregunta == 'motivo':
                motivo = texto

        solicitud_datos_personales = responder_en_cada_turno(
            [
                'datos personales', 'datos bancarios', 'numero de cuenta', 'numero de tarjeta',
                'dni', 'cedula', 'curp', 'rfc', 'fecha de nacimiento', 'domicilio',
                'identificacion oficial', 'ine', 'pasaporte', 'clabe interbancaria',
            ]
        )
        solicitud_contrasenas = responder_en_cada_turno(
            [
                'contraseña', 'password', 'nip', 'pin', 'clave de acceso', 'clave dinamica',
                'codigo de seguridad', 'cvv', 'cvc', 'otp', 'token', 'passcode',
                'firma electronica', 'e firma', 'llave digital', 'codigo de autenticacion',
            ]
        )
        solicitud_codigos_bancarios = responder_en_cada_turno(
            [
                'codigo bancario', 'clabe', 'codigo de verificacion', 'codigo que te llego por sms',
                'codigo que recibiste por mensaje', 'codigo enviado a tu celular', 'cvu',
                'codigo de seguridad', 'codigo de un solo uso', 'otp', 'token bancario',
            ]
        )
        solicitud_transferencias = responder_en_cada_turno(
            [
                'transferencia', 'transferir', 'transfiere el dinero', 'movimiento de dinero',
                'mover dinero', 'pago inmediato', 'pago hoy', 'hacer un pago', 'pagar', 'abonar',
                'depositar', 'enviar dinero', 'tarjetas de regalo', 'realizar un spei',
                'mandar un spei', 'agregar un beneficiario', 'retirar dinero', 'compra no reconocida',
            ]
        )
        amenazas_o_intimidacion = _es_amenaza_explicita(texto_join)
        urgencia = bool(re.search(r'\b(?:hoy mismo|de inmediato|urgente|asunto urgente|sin perder tiempo|ahora mismo|ultima oportunidad|no cuelgues|en este momento|inmediatamente)\b', _normalizar_texto_nlp(texto_join)))
        pide_accion = any((solicitud_datos_personales, solicitud_contrasenas, solicitud_codigos_bancarios, solicitud_transferencias))
        presion_para_actuar = urgencia and pide_accion
        respuestas_fuera_contexto = [
            respuesta for respuesta in respuestas
            if self.limpiar_texto(respuesta.texto_respuesta)
            and _respuesta_desalineada(respuesta.pregunta.codigo, respuesta.texto_respuesta)
        ]
        calidad = _evaluar_calidad_respuestas(respuestas)
        inconsistencias = bool(respuestas_fuera_contexto) or calidad['respuestas_contradictorias']
        texto_norm = _normalizar_texto_nlp(texto_join)
        evasiva = bool(re.search(
            r'\b(?:no puedo decir|no lo se|eso no importa|no quiero responder|prefiero no comentar|no le digas a nadie|mantenga esto en secreto|no voy a identificarme|no tengo que contestar|no es asunto suyo|solo quiero hablar|solo comuniqueme|ya quiero hablar|paseme con la persona|no es asunto suyo)\b',
            texto_norm,
        )) or inconsistencias or calidad['respuestas_vagas'] or calidad['respuestas_repetitivas'] or calidad['faltan_respuestas']
        insistencia_sin_identificarse = any(
            _demanda_hablar_con_persona(r.texto_respuesta)
            and (r.pregunta.codigo.lower() in {'nombre', 'institucion', 'motivo'})
            and _respuesta_desalineada(r.pregunta.codigo, r.texto_respuesta)
            for r in respuestas if self.limpiar_texto(r.texto_respuesta)
        )

        indicadores = []
        if solicitud_datos_personales:
            indicadores.append('solicitud de datos personales')
        if solicitud_contrasenas:
            indicadores.append('solicitud de contraseñas')
        if solicitud_codigos_bancarios:
            indicadores.append('solicitud de códigos bancarios')
        if solicitud_transferencias:
            indicadores.append('solicitud de transferencias')
        if amenazas_o_intimidacion:
            indicadores.append('amenazas o intimidación')
        if presion_para_actuar:
            indicadores.append('presión para actuar inmediatamente')
        elif insistencia_sin_identificarse:
            indicadores.append('insistencia por hablar con otra persona sin identificarse')
        if inconsistencias:
            indicadores.append('respuestas contradictorias o fuera de contexto')
        if calidad['respuestas_vagas']:
            indicadores.extend(calidad['motivos_vaguedad'])
        if calidad['respuestas_repetitivas']:
            indicadores.append('respuestas repetitivas')
        if calidad['faltan_respuestas']:
            indicadores.append('información insuficiente')
        if evasiva:
            indicadores.append('evasión de preguntas')

        if solicitud_datos_personales or solicitud_contrasenas or solicitud_codigos_bancarios or solicitud_transferencias or amenazas_o_intimidacion:
            clasificacion = ClasificacionAnalisis.ALERTA
            explicacion = 'Se detectaron indicadores importantes de posible fraude: solicitudes sensibles, transferencias o presión para actuar sin verificar.'
        elif not texto_join.strip() or calidad['faltan_respuestas'] or calidad['respuestas_vagas'] or calidad['respuestas_repetitivas']:
            clasificacion = ClasificacionAnalisis.INTERMEDIO
            explicacion = 'La información no es suficiente o las respuestas fueron vagas o repetitivas. Mantén precaución y verifica la identidad por un canal oficial antes de continuar.'
        elif not indicadores:
            clasificacion = ClasificacionAnalisis.SEGURO
            explicacion = 'La información disponible está sin indicadores importantes de fraude; la llamada no presenta solicitudes sospechosas ni presión indebida.'
        elif insistencia_sin_identificarse or inconsistencias or evasiva:
            clasificacion = ClasificacionAnalisis.INTERMEDIO
            explicacion = 'La persona insistió en hablar sin identificarse, repitió respuestas o no respondió de forma coherente. Esto requiere precaución, pero por sí solo no confirma una amenaza; verifica por un canal oficial.'
        else:
            clasificacion = ClasificacionAnalisis.INTERMEDIO
            explicacion = 'Hay inconsistencias o señales sospechosas que requieren verificar antes de aceptar la llamada.'

        return {
            'identidad_declarada': nombre,
            'institucion': institucion,
            'motivo': motivo,
            'solicitud_datos_personales': solicitud_datos_personales,
            'solicitud_contrasenas': solicitud_contrasenas,
            'solicitud_codigos_bancarios': solicitud_codigos_bancarios,
            'solicitud_transferencias': solicitud_transferencias,
            'amenazas_o_intimidacion': amenazas_o_intimidacion,
            'presion_para_actuar_inmediatamente': presion_para_actuar,
            'inconsistencias': inconsistencias,
            'evasiva_de_preguntas': evasiva,
            'indicadores_detectados': '; '.join(indicadores) if indicadores else 'Sin indicadores clave detectados.',
            'clasificacion': clasificacion,
            'nivel_confianza': 0.76 if clasificacion == ClasificacionAnalisis.SEGURO else 0.62 if clasificacion == ClasificacionAnalisis.INTERMEDIO else 0.88,
            'explicacion': explicacion,
            'antecedentes_consultados': str(antecedentes or []),
            'transcripciones_consultadas': str(transcripciones or []),
        }


def _mapear_nivel_riesgo(clasificacion):
    mapping = {
        ClasificacionAnalisis.SEGURO: NivelRiesgoResumen.BAJO,
        ClasificacionAnalisis.INTERMEDIO: NivelRiesgoResumen.MEDIO,
        ClasificacionAnalisis.ALERTA: NivelRiesgoResumen.ALTO,
        ClasificacionAnalisis.INFORMACION_INSUFICIENTE: NivelRiesgoResumen.SIN_EVALUAR,
    }
    return mapping.get(clasificacion, NivelRiesgoResumen.SIN_EVALUAR)


def generar_resumen_llamada(llamada):
    """Genera un resumen comprensible para el adulto mayor usando datos ya validados del análisis."""
    analisis = getattr(llamada, 'analisis_llamada', None)
    if analisis is None:
        analisis = analizar_llamada(llamada)

    identidad = (analisis.identidad_declarada or '').strip() or 'No identificado'
    institucion = (analisis.institucion or '').strip() or 'No identificada'
    motivo = (analisis.motivo or '').strip() or 'No se pudo determinar el motivo de la llamada'
    indicadores = (analisis.indicadores_detectados or '').strip() or 'No se detectaron indicadores clave.'
    nivel_riesgo = _mapear_nivel_riesgo(analisis.clasificacion)
    explicacion = (analisis.explicacion or '').strip() or 'Se requiere revisar la información antes de decidir.'

    if identidad == 'No identificado':
        identidad_texto = 'No identificado. El llamante no fue identificado.'
    else:
        identidad_texto = f'El llamante dice llamarse {identidad}.'

    if institucion == 'No identificada':
        institucion_texto = 'No identificada. La institución no fue identificada.'
    else:
        institucion_texto = f'El llamante afirma comunicarse de parte de {institucion}; esta afirmación no confirma su identidad.'

    if motivo == 'No se pudo determinar el motivo de la llamada':
        motivo_texto = 'No se pudo determinar el motivo de la llamada.'
    else:
        motivo_texto = f'El motivo mencionado es: {motivo}.'

    solicitudes = []
    if analisis.solicitud_datos_personales:
        solicitudes.append('solicita información personal o bancaria')
    if analisis.solicitud_contrasenas:
        solicitudes.append('solicita contraseñas o códigos de seguridad')
    if analisis.solicitud_codigos_bancarios:
        solicitudes.append('solicita claves bancarias')
    if analisis.solicitud_transferencias:
        solicitudes.append('solicita transferencias o pagos inmediatos')
    if analisis.amenazas_o_intimidacion:
        solicitudes.append('menciona amenazas o presión')

    if solicitudes:
        solicitudes_texto = f'Se identificaron solicitudes sospechosas: {"; ".join(solicitudes)}.'
    else:
        solicitudes_texto = 'No se detectaron solicitudes sospechosas.'

    if nivel_riesgo == NivelRiesgoResumen.ALTO:
        resumen_texto = (
            f'{identidad_texto} {institucion_texto} {motivo_texto} {solicitudes_texto} '
            'PELIGRO. Nivel de riesgo: ALTO.'
        )
    elif nivel_riesgo == NivelRiesgoResumen.MEDIO:
        resumen_texto = (
            f'{identidad_texto} {institucion_texto} {motivo_texto} {solicitudes_texto} '
            'Nivel de riesgo: MEDIO.'
        )
    elif nivel_riesgo == NivelRiesgoResumen.BAJO:
        resumen_texto = (
            f'{identidad_texto} {institucion_texto} {motivo_texto} {solicitudes_texto} '
            'Nivel de riesgo: BAJO.'
        )
    else:
        resumen_texto = (
            f'{identidad_texto} {institucion_texto} {motivo_texto} {solicitudes_texto} '
            'Nivel de riesgo: SIN EVALUAR.'
        )

    resumen, created = ResumenLlamada.objects.update_or_create(
        llamada=llamada,
        defaults={
            'identidad_declarada': identidad,
            'institucion': institucion,
            'motivo': motivo,
            'indicadores_detectados': indicadores,
            'clasificacion': analisis.clasificacion,
            'nivel_riesgo': nivel_riesgo,
            'explicacion': explicacion,
            'texto_resumen': resumen_texto,
        },
    )
    return resumen


def detectar_indicios_fraude(transcripcion):
    """Detecta indicadores de fraude a partir de la transcripción de una llamada."""
    if isinstance(transcripcion, (str, bytes)):
        texto = (transcripcion or '').strip()
        llamada = None
        transcripcion_obj = None
    else:
        transcripcion_obj = transcripcion
        texto = (getattr(transcripcion, 'texto_transcrito', '') or '').strip()
        llamada = getattr(transcripcion, 'llamada', None)

    if not texto:
        return IndicadorFraude.objects.none()

    catalogo = {
        'solicitud_nip': {
            'nombre': 'Solicitud de NIP',
            'descripcion': 'Se solicita información confidencial de acceso.',
            'patrones': ['nip', 'pin', 'código personal', 'numero secreto', 'código de acceso', 'clave dinamica', 'llave digital'],
            'gravedad': 'ALTA',
        },
        'solicitud_contrasenas': {
            'nombre': 'Solicitud de contraseñas',
            'descripcion': 'Se solicita una contraseña o clave secreta.',
            'patrones': ['contraseña', 'password', 'clave secreta', 'clave de acceso', 'token bancario', 'firma electronica', 'e firma'],
            'gravedad': 'ALTA',
        },
        'solicitud_cvv': {
            'nombre': 'Solicitud de CVV',
            'descripcion': 'Se pide el CVV o código de tarjeta.',
            'patrones': ['cvv', 'cvc', 'código de seguridad de tarjeta', 'código de tarjeta'],
            'gravedad': 'ALTA',
        },
        'solicitud_codigos_verificacion': {
            'nombre': 'Solicitud de códigos de verificación',
            'descripcion': 'Se pide un código enviado por SMS o autenticación.',
            'patrones': ['código de verificación', 'código de seguridad', 'otp', 'código enviado', 'código de un solo uso', 'token bancario'],
            'gravedad': 'ALTA',
        },
        'solicitud_datos_bancarios': {
            'nombre': 'Solicitud de datos bancarios',
            'descripcion': 'Se solicita información financiera sensible.',
            'patrones': ['datos bancarios', 'cuenta bancaria', 'clabe', 'clabe interbancaria', 'número de cuenta', 'número de tarjeta', 'datos personales', 'curp', 'rfc', 'fecha de nacimiento'],
            'gravedad': 'ALTA',
        },
        'solicitud_transferencias': {
            'nombre': 'Solicitud de transferencias',
            'descripcion': 'Se exige realizar una transferencia o pago.',
            'patrones': ['transferencia', 'transferir dinero', 'pago inmediato', 'depositar', 'realizar un spei', 'agregar un beneficiario', 'mandar un spei'],
            'gravedad': 'ALTA',
        },
        'amenazas': {
            'nombre': 'Amenazas',
            'descripcion': 'Se usan amenazas o intimidación.',
            'patrones': ['si no', 'se bloqueará', 'te va a pasar algo', 'amenaza', 'si no paga'],
            'gravedad': 'CRITICA',
        },
        'intimidacion': {
            'nombre': 'Intimidación',
            'descripcion': 'Se presiona con intimidación o urgencia indebida.',
            'patrones': ['urgente', 'de inmediato', 'sin perder tiempo', 'porque si no', 'de lo contrario'],
            'gravedad': 'ALTA',
        },
        'acceso_remoto': {
            'nombre': 'Solicitud de acceso remoto',
            'descripcion': 'Se pide instalar una herramienta o compartir el control del dispositivo.',
            'patrones': ['anydesk', 'teamviewer', 'rustdesk', 'quick support', 'acceso remoto', 'compartir pantalla', 'controlar su celular'],
            'gravedad': 'ALTA',
        },
    }

    def normalizar(texto):
        texto = unicodedata.normalize('NFD', (texto or '').lower())
        return ''.join(caracter for caracter in texto if unicodedata.category(caracter) != 'Mn')

    texto_normalizado = normalizar(texto)
    patrones_db = list(PatronFraude.objects.filter(activo=True))
    if patrones_db:
        for patron_db in patrones_db:
            item = catalogo.setdefault(patron_db.codigo, {
                'nombre': patron_db.nombre,
                'descripcion': patron_db.descripcion,
                'patrones': [],
                'gravedad': patron_db.gravedad,
            })
            if patron_db.patron not in item['patrones']:
                item['patrones'].append(patron_db.patron)

    indicadores_creados = []
    for codigo, detalle in catalogo.items():
        for patron in detalle['patrones']:
            patron_norm = normalizar(patron)
            coincidencia = re.search(r'(?<!\w)' + re.escape(patron_norm) + r'(?!\w)', texto_normalizado)
            if coincidencia:
                codigo_norm = codigo.lower()
                if codigo_norm in {'credenciales', 'codigos', 'tarjeta', 'datos_bancarios', 'transferencias', 'solicitud_nip', 'solicitud_contrasenas', 'solicitud_cvv', 'solicitud_codigos_verificacion', 'solicitud_datos_bancarios', 'solicitud_transferencias', 'acceso_remoto'}:
                    if not _es_solicitud_activa(texto, patron):
                        continue
                elif codigo_norm in {'amenaza', 'amenazas', 'intimidacion'}:
                    if not _es_amenaza_explicita(texto):
                        continue
                elif codigo_norm == 'urgencia':
                    accion = any(_es_solicitud_activa(texto, termino) for termino in (
                        'contraseña', 'codigo de verificacion', 'nip', 'cvv', 'datos bancarios',
                        'transferencia', 'deposito', 'pago', 'instala esta aplicacion',
                        'descarga esta app', 'descarga esta aplicacion', 'comparte tu pantalla',
                        'activa el acceso remoto', 'abre el enlace',
                    ))
                    if not accion:
                        continue
                # La mención aislada de una palabra no se guarda como señal de fraude.
                inicio = coincidencia.start()
                fragmento = texto[max(0, inicio - 120): min(len(texto), inicio + len(patron) + 120)]
                if not llamada:
                    continue
                indicador, created = IndicadorFraude.objects.get_or_create(
                    llamada=llamada,
                    transcripcion=transcripcion_obj,
                    codigo=codigo,
                    patron=patron,
                    defaults={
                        'nombre': detalle['nombre'],
                        'descripcion': detalle['descripcion'],
                        'fragmento': fragmento,
                        'gravedad': detalle['gravedad'],
                    },
                )
                indicadores_creados.append(indicador)
                break

    return IndicadorFraude.objects.filter(pk__in=[obj.pk for obj in indicadores_creados])


def clasificar_llamada(llamada):
    """Clasifica el nivel de riesgo usando indicadores de fraude, análisis NLP y penalización por falta de evidencia."""
    transcripciones = list(llamada.transcripciones.all())
    for transcripcion in transcripciones:
        if transcripcion.texto_transcrito:
            detectar_indicios_fraude(transcripcion)

    indicadores = list(IndicadorFraude.objects.filter(llamada=llamada, activo=True))
    analisis = getattr(llamada, 'analisis_llamada', None)

    texto_transcrito = ' '.join(item.texto_transcrito.strip() for item in transcripciones if item.texto_transcrito and item.texto_transcrito.strip())
    respuestas = list(llamada.respuestas_llamada.all())
    texto_respuestas = ' '.join(item.texto_respuesta.strip() for item in respuestas if item.texto_respuesta and item.texto_respuesta.strip())
    texto_valido = ' '.join(texto for texto in (texto_transcrito, texto_respuestas) if texto)
    evidencia_valida = bool(texto_valido) and len(re.findall(r'[A-Za-zÁÉÍÓÚáéíóúÑñ]', texto_valido)) >= 8

    score = 0
    senales = []
    for indicador in indicadores:
        clave = indicador.codigo.lower()
        puntos = {
            'solicitud_nip': 35,
            'solicitud_contrasenas': 35,
            'solicitud_cvv': 35,
            'solicitud_codigos_verificacion': 35,
            'solicitud_datos_bancarios': 30,
            'solicitud_transferencias': 30,
            'acceso_remoto': 70,
            'amenazas': 40,
            'intimidacion': 28,
            'urgencia': 8,
            'suplantacion': 8,
        }.get(clave, 10)
        puntuacion_catalogo = PatronFraude.objects.filter(patron=indicador.patron, activo=True).values_list('puntuacion', flat=True).first()
        if puntuacion_catalogo is not None:
            puntos = puntuacion_catalogo
        if clave == 'urgencia':
            puntos = min(puntos, 10)
        elif clave == 'suplantacion':
            puntos = min(puntos, 12)
        elif clave in {
            'solicitud_nip', 'solicitud_contrasenas', 'solicitud_cvv',
            'solicitud_codigos_verificacion', 'solicitud_datos_bancarios',
            'solicitud_transferencias', 'acceso_remoto', 'amenazas', 'amenaza',
        }:
            # Estos indicadores solo se crean tras confirmar una petición activa
            # (o una amenaza explícita), por eso justifican riesgo alto por sí solos.
            puntos = max(puntos, 70)
        score += puntos
        senales.append(indicador.nombre)

    if any(item.gravedad == 'CRITICA' for item in indicadores):
        score = max(score, 70)

    if analisis is not None:
        if analisis.solicitud_contrasenas:
            score = max(score, 70)
            senales.append('Solicitud de contraseña o credencial')
        if analisis.solicitud_codigos_bancarios:
            score = max(score, 70)
            senales.append('Solicitud de código bancario o de verificación')
        if analisis.solicitud_transferencias:
            score = max(score, 70)
            senales.append('Solicitud de transferencia o pago')
        if analisis.solicitud_datos_personales:
            score = max(score, 70)
            senales.append('Solicitud de datos personales o bancarios')
        if analisis.amenazas_o_intimidacion:
            score = max(score, 70)
            senales.append('Amenaza o consecuencia coercitiva explícita')
        if analisis.inconsistencias or analisis.evasiva_de_preguntas:
            score = max(score, 30)
            senales.append('Respuestas vagas, repetidas, contradictorias o incompletas')
            detalle_respuestas = [
                item.strip() for item in analisis.indicadores_detectados.split(';')
                if item.strip() and item.strip() != 'Sin indicadores clave detectados.'
            ]
            senales.extend(detalle_respuestas)

    solicitudes_sensibles = (
        'contraseña', 'nip', 'pin', 'cvv', 'codigo de verificacion', 'codigo de seguridad',
        'datos bancarios', 'numero de tarjeta', 'clabe', 'transferencia', 'depositar',
        'pagar', 'realizar un spei', 'instala anydesk', 'instala teamviewer',
        'compartir pantalla', 'acceso remoto',
    )
    peticion_sensible_sin_indicador = any(
        _es_solicitud_activa(texto_valido, termino) for termino in solicitudes_sensibles
    )
    if peticion_sensible_sin_indicador and not indicadores and analisis is None:
        score = max(score, 70)
        senales.append('Petición directa de información sensible o acción financiera')

    if not evidencia_valida:
        score = int(score * 0.6)
        # Sin evidencia suficiente no se debe presentar la llamada como segura.
        score = max(score, 30)

    prediccion_modelo = _predecir_riesgo_nlp(texto_valido)
    if prediccion_modelo is not None:
        probabilidad_fraude, etiqueta_modelo = prediccion_modelo
        if probabilidad_fraude >= 0.85:
            evidencia_concreta_alta = bool(
                analisis and (
                    analisis.solicitud_contrasenas
                    or analisis.solicitud_codigos_bancarios
                    or analisis.solicitud_transferencias
                    or analisis.solicitud_datos_personales
                    or analisis.amenazas_o_intimidacion
                )
            ) or any(item.gravedad == 'CRITICA' for item in indicadores)
            if evidencia_concreta_alta:
                score = max(score, 70)
                senales.append(f'Modelo de lenguaje local corroborado por señales concretas ({probabilidad_fraude:.0%})')
            else:
                score = max(score, 30)
                senales.append('El modelo sugiere revisar, pero no se confirmó una solicitud sensible o amenaza')
        elif probabilidad_fraude >= 0.65:
            score = max(score, 30)
            senales.append(f'Modelo de lenguaje local: requiere revisión ({probabilidad_fraude:.0%})')
    score = min(score, 100)

    if score >= 70:
        nivel = 'ROJO'
        if analisis is not None and analisis.amenazas_o_intimidacion:
            motivo = 'PELIGRO. Se detectó una amenaza explícita o una consecuencia coercitiva; termina la llamada y verifica por un canal oficial.'
        else:
            motivo = 'PELIGRO. Se detectó una solicitud de credenciales, códigos, pagos u otra acción de alto riesgo.'
    elif score >= 30:
        nivel = 'AMARILLO'
        if not evidencia_valida:
            motivo = 'No hay suficiente información para evaluar la llamada. Verifica la identidad por un canal oficial antes de confiar en ella.'
        elif analisis is not None and (analisis.inconsistencias or analisis.evasiva_de_preguntas) and not analisis.amenazas_o_intimidacion:
            motivo = 'Hubo respuestas vagas, repetidas, contradictorias o incompletas. Esto requiere precaución, pero no confirma por sí solo una amenaza; verifica la identidad por un canal oficial.'
        else:
            motivo = 'Se requieren precauciones. Hay señales sospechosas o información incompleta.'
    else:
        nivel = 'VERDE'
        motivo = 'No se identificaron indicadores importantes de fraude.'

    ClasificacionRiesgo.objects.filter(llamada=llamada).update(es_actual=False)
    clasificacion = ClasificacionRiesgo.objects.create(
        llamada=llamada,
        nivel=nivel,
        puntuacion=score,
        motivo=motivo,
        señales='; '.join(dict.fromkeys(senales)) if senales else 'Sin señales detectadas',
        es_actual=True,
    )
    from .notificaciones import generar_evento_notificacion
    generar_evento_notificacion(llamada, clasificacion=clasificacion)
    return clasificacion


def analizar_llamada(llamada):
    """Procesa respuestas, antecedentes y transcripciones de la llamada para generar un análisis estructurado."""
    respuestas = list(RespuestaLlamada.objects.filter(llamada=llamada).select_related('pregunta'))
    antecedentes = list(llamada.consultas_numero.all())
    transcripciones = list(llamada.transcripciones.all())

    preguntas_configuradas = obtener_preguntas_agente()

    respuesta_map = {r.pregunta.codigo.lower(): r for r in respuestas}
    for pregunta in preguntas_configuradas:
        if pregunta.codigo.lower() not in respuesta_map:
            RespuestaLlamada.objects.create(
                llamada=llamada,
                pregunta=pregunta,
                texto_respuesta='',
            )

    respuestas_actualizadas = list(RespuestaLlamada.objects.filter(llamada=llamada).select_related('pregunta'))
    resultado = AdaptadorNlpPrototipo().analizar(respuestas_actualizadas, antecedentes, transcripciones)

    indicadores_catalogo = list(IndicadorFraude.objects.filter(llamada=llamada, activo=True))
    amenaza_en_transcripcion = _es_amenaza_explicita(' '.join(item.texto_transcrito for item in transcripciones if item.texto_transcrito))
    resultado['amenazas_o_intimidacion'] |= amenaza_en_transcripcion
    codigos_criticos = {'codigos', 'credenciales', 'tarjeta', 'datos_bancarios', 'transferencias', 'amenaza', 'secreto', 'acceso_remoto'}
    codigos_sospechosos = {'urgencia', 'enlaces', 'suplantacion', 'entrega'}
    codigos_detectados = {item.codigo for item in indicadores_catalogo}
    if codigos_detectados & codigos_criticos:
        resultado['clasificacion'] = ClasificacionAnalisis.ALERTA
        resultado['nivel_confianza'] = max(resultado['nivel_confianza'], 0.85)
        resultado['explicacion'] = 'La transcripción contiene una solicitud o táctica de alto riesgo. No comparta datos ni realice pagos; verifique por un canal oficial independiente.'
        existentes = [] if resultado['indicadores_detectados'] == 'Sin indicadores clave detectados.' else [resultado['indicadores_detectados']]
        resultado['indicadores_detectados'] = '; '.join(dict.fromkeys(existentes + [item.nombre for item in indicadores_catalogo]))
        resultado['solicitud_contrasenas'] |= bool(codigos_detectados & {'credenciales', 'codigos'})
        resultado['solicitud_codigos_bancarios'] |= 'codigos' in codigos_detectados
        resultado['solicitud_transferencias'] |= 'transferencias' in codigos_detectados
        # Urgencia o aislamiento aumentan el riesgo de fraude, pero no equivalen por sí solos a una amenaza.
        resultado['amenazas_o_intimidacion'] |= 'amenaza' in codigos_detectados
    elif codigos_detectados & codigos_sospechosos and resultado['clasificacion'] == ClasificacionAnalisis.SEGURO:
        resultado['clasificacion'] = ClasificacionAnalisis.INTERMEDIO
        resultado['explicacion'] = 'Se detectaron tácticas sospechosas. Verifique la identidad y el motivo por un canal oficial antes de continuar.'

    analisis, created = AnalisisLlamada.objects.update_or_create(
        llamada=llamada,
        defaults={
            'identidad_declarada': resultado['identidad_declarada'],
            'institucion': resultado['institucion'],
            'motivo': resultado['motivo'],
            'solicitud_datos_personales': resultado['solicitud_datos_personales'],
            'solicitud_contrasenas': resultado['solicitud_contrasenas'],
            'solicitud_codigos_bancarios': resultado['solicitud_codigos_bancarios'],
            'solicitud_transferencias': resultado['solicitud_transferencias'],
            'amenazas_o_intimidacion': resultado['amenazas_o_intimidacion'],
            'presion_para_actuar_inmediatamente': resultado['presion_para_actuar_inmediatamente'],
            'inconsistencias': resultado['inconsistencias'],
            'evasiva_de_preguntas': resultado['evasiva_de_preguntas'],
            'indicadores_detectados': resultado['indicadores_detectados'],
            'clasificacion': resultado['clasificacion'],
            'nivel_confianza': resultado['nivel_confianza'],
            'explicacion': resultado['explicacion'],
            'antecedentes_consultados': resultado['antecedentes_consultados'],
            'transcripciones_consultadas': resultado['transcripciones_consultadas'],
        },
    )
    return analisis
