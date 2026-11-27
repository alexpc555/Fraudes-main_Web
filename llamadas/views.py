import json
import uuid

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .forms import AudioLlamadaForm, ContactoConfianzaForm, FamiliarSinCuentaForm, NumeroReportadoForm, RegistrarLlamadaForm
from .models import AnalisisLlamada, ConfiguracionAplicacion, ConfiguracionNotificaciones, ContactoConfianza, EstadoConsultaNumero, EstadoConversacion, EstadoLlamada, EstadoPermiso, Llamada, NumeroReportado, RelacionFamiliarAdultoMayor, SesionConversacion, TranscripcionLlamada
from .configuracion_services import (
    actualizar_estado_permiso,
    obtener_estado_configuracion,
    obtener_o_crear_configuracion,
    registrar_configuracion_completada,
    verificar_autorizacion_configuracion,
)
from .notificaciones import (
    guardar_contacto_notificacion_sin_cuenta,
    guardar_contacto_notificacion,
    obtener_configuracion_notificaciones,
    obtener_configuracion_notificaciones_sin_cuenta,
    obtener_contactos_notificacion,
)
from .contenido_ayuda import TEMAS_AYUDA, TEMAS_POR_SLUG
from .services import (
    analizar_llamada,
    AgenteVoz,
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
from .speech_to_text import transcribir_audio

User = get_user_model()


def obtener_usuario_protegido(request):
    if request.user.is_authenticated:
        return request.user
    usuario_id = request.session.get('perfil_adulto_sin_cuenta_id')
    if usuario_id:
        usuario = User.objects.filter(pk=usuario_id).first()
        if usuario:
            return usuario

    # Conserva los datos del perfil anterior de una sola instalación y lo vincula
    # a esta sesión. Los siguientes visitantes tendrán su propio perfil sin cuenta.
    usuario = User.objects.filter(username='usuario_protegido').first()
    username = f'adulto_sin_cuenta_{uuid.uuid4().hex[:24]}'
    if usuario is None:
        usuario = User(username=username)
        usuario.set_unusable_password()
        usuario.save()
    else:
        usuario.username = username
        usuario.set_unusable_password()
        usuario.save(update_fields=['username', 'password'])
    request.session['perfil_adulto_sin_cuenta_id'] = usuario.pk
    return usuario


def _usuario_propietario_contactos(request):
    """Usa la agenda del Adulto mayor elegido y vuelve a validar su autorización."""
    adulto_id = request.session.get('cu20_adulto_mayor_id')
    if adulto_id:
        adulto = User.objects.filter(pk=adulto_id).first()
        if adulto is None or not verificar_autorizacion_configuracion(request.user, adulto):
            raise PermissionDenied('Ya no tienes autorización para modificar estos contactos.')
        return adulto
    return obtener_usuario_protegido(request)


def _adulto_mayor_para_llamada(request, adulto_id=None):
    """Vincula la llamada al perfil autorizado actual para enrutar alertas familiares."""
    seleccionado = adulto_id or request.session.get('cu20_adulto_mayor_id')
    if request.user.is_authenticated:
        if seleccionado:
            adulto = User.objects.filter(pk=seleccionado).first()
            if adulto and verificar_autorizacion_configuracion(request.user, adulto):
                return adulto
            if request.session.get('cu20_adulto_mayor_id'):
                raise PermissionDenied('No tienes autorización para este dispositivo.')
        relaciones = RelacionFamiliarAdultoMayor.objects.filter(familiar=request.user, autorizado=True).select_related('adulto_mayor')
        if relaciones.count() == 1:
            return relaciones.first().adulto_mayor
        if relaciones.exists():
            return None
        return request.user
    return obtener_usuario_protegido(request)


def _registrar_cambio_contactos(request, adulto_mayor):
    adulto_id = request.session.get('cu20_adulto_mayor_id')
    if not adulto_id or adulto_mayor.pk != adulto_id or not request.user.is_authenticated:
        return
    if not verificar_autorizacion_configuracion(request.user, adulto_mayor):
        raise PermissionDenied('No tienes autorización para modificar estos contactos.')
    configuracion = ConfiguracionAplicacion.objects.filter(adulto_mayor=adulto_mayor).first()
    if configuracion:
        configuracion.actualizado_por = request.user
        configuracion.completado_por = None
        configuracion.completado_en = None
        configuracion.save(update_fields=['actualizado_por', 'actualizado_en', 'completado_por', 'completado_en'])
        obtener_estado_configuracion(request.user, adulto_mayor)


@login_required
def configuracion_inicio(request):
    relaciones = RelacionFamiliarAdultoMayor.objects.filter(
        familiar=request.user,
        autorizado=True,
    ).select_related('adulto_mayor')
    cantidad = relaciones.count()
    if cantidad == 0:
        return render(request, 'llamadas/configuracion_denegada.html', status=403)
    if cantidad == 1:
        return redirect('configuracion_aplicacion', adulto_id=relaciones.first().adulto_mayor_id)
    return render(request, 'llamadas/configuracion_seleccionar.html', {'relaciones': relaciones})


@login_required
def configuracion_aplicacion(request, adulto_id):
    adulto = get_object_or_404(User, pk=adulto_id)
    if not verificar_autorizacion_configuracion(request.user, adulto):
        return render(request, 'llamadas/configuracion_denegada.html', status=403)
    request.session['cu20_adulto_mayor_id'] = adulto.pk

    configuracion = obtener_o_crear_configuracion(request.user, adulto)
    pasos = [choice for choice, _ in ConfiguracionAplicacion.Paso.choices]
    paso = request.POST.get('paso') if request.method == 'POST' else request.GET.get('paso')
    if paso not in pasos:
        paso = configuracion.paso_actual
    indice = pasos.index(paso)

    if request.method == 'POST':
        accion = request.POST.get('accion', '')
        try:
            if accion == 'actualizar_permiso':
                actualizar_estado_permiso(
                    request.user,
                    adulto,
                    request.POST.get('codigo', ''),
                    request.POST.get('estado', ''),
                )
                messages.success(request, 'Se guardó el estado del permiso. Android deberá confirmar los permisos concedidos.')
            elif accion == 'guardar_notificaciones':
                preferencia = request.POST.get('notificaciones_habilitadas') == 'on'
                if configuracion.notificaciones_habilitadas != preferencia:
                    configuracion.completado_en = None
                    configuracion.completado_por = None
                configuracion.notificaciones_habilitadas = preferencia
                configuracion.actualizado_por = request.user
                configuracion.save(update_fields=['notificaciones_habilitadas', 'actualizado_por', 'actualizado_en'])
                messages.success(request, 'Se guardó la preferencia de notificaciones.')
            elif accion == 'anterior':
                indice = max(0, indice - 1)
            elif accion == 'siguiente':
                indice = min(len(pasos) - 1, indice + 1)
            elif accion == 'finalizar':
                if registrar_configuracion_completada(request.user, adulto):
                    messages.success(request, 'La configuración está completa.')
                else:
                    messages.warning(request, 'Aún hay pasos pendientes. Revisa los permisos, contactos y notificaciones.')
                indice = len(pasos) - 1
            configuracion.paso_actual = pasos[indice]
            configuracion.actualizado_por = request.user
            configuracion.save(update_fields=['paso_actual', 'actualizado_por', 'actualizado_en'])
        except ValidationError as exc:
            messages.error(request, 'No se pudo guardar el cambio: ' + '; '.join(exc.messages))
        return redirect(f'{reverse("configuracion_aplicacion", kwargs={"adulto_id": adulto.pk})}?paso={pasos[indice]}')

    estado = obtener_estado_configuracion(request.user, adulto)
    indice = pasos.index(paso)
    return render(request, 'llamadas/configuracion_aplicacion.html', {
        'adulto': adulto,
        'configuracion': configuracion,
        'estado': estado,
        'contactos': ContactoConfianza.objects.filter(usuario_protegido=adulto, activo=True),
        'paso': paso,
        'indice_paso': indice,
        'total_pasos': len(pasos),
        'progreso': int((indice + 1) * 100 / len(pasos)),
        'pasos': ConfiguracionAplicacion.Paso.choices,
        'estados_permiso': [
            (EstadoPermiso.Estado.PENDIENTE, 'Pendiente de solicitar'),
            (EstadoPermiso.Estado.DENEGADO, 'Denegado'),
            (EstadoPermiso.Estado.NO_DISPONIBLE, 'No disponible en el dispositivo'),
        ],
        'contactos_url': reverse('configuracion_contactos', kwargs={'adulto_id': adulto.pk}),
    })


def familiar_opcional(request):
    """Permite añadir un familiar para avisos desde el perfil local, sin login."""
    adulto = _usuario_propietario_contactos(request)
    notificacion = obtener_configuracion_notificaciones_sin_cuenta(adulto)
    contacto_actual = notificacion.contacto_confianza if notificacion else None
    form = FamiliarSinCuentaForm(request.POST or None, instance=contacto_actual)
    form.usuario_protegido = adulto
    if contacto_actual is None:
        form.fields['relacion'].initial = 'Familiar de confianza'

    if request.method == 'POST':
        if request.POST.get('confirmar_familiar') != 'on':
            form.add_error(None, 'Confirma que esta persona es tu familiar de confianza.')
        if form.is_valid():
            contacto = form.save(commit=False)
            contacto.usuario_protegido = adulto
            contacto.activo = True
            if not contacto.relacion:
                contacto.relacion = 'Familiar de confianza'
            contacto.save()
            try:
                guardar_contacto_notificacion_sin_cuenta(
                    adulto,
                    contacto.pk,
                    confirmar=request.POST.get('confirmar_familiar') == 'on',
                )
            except ValidationError as exc:
                messages.error(request, '; '.join(exc.messages))
            else:
                messages.success(request, 'El familiar quedó configurado para recibir avisos. La protección de llamadas funciona aunque no agregues un familiar.')
                return redirect('familiar_opcional')
        else:
            messages.error(request, 'Revisa los datos del familiar e intenta guardar de nuevo.')

    return render(request, 'llamadas/familiar_opcional.html', {
        'form': form,
        'contacto_actual': contacto_actual,
    })


@login_required
def configuracion_contactos(request, adulto_id):
    adulto = get_object_or_404(User, pk=adulto_id)
    if not verificar_autorizacion_configuracion(request.user, adulto):
        return render(request, 'llamadas/configuracion_denegada.html', status=403)
    obtener_o_crear_configuracion(request.user, adulto)
    request.session['cu20_adulto_mayor_id'] = adulto.pk
    return redirect('lista_contactos')


@login_required
def configurar_notificaciones(request, adulto_id):
    adulto = get_object_or_404(User, pk=adulto_id)
    if not verificar_autorizacion_configuracion(request.user, adulto):
        return render(request, 'llamadas/configuracion_denegada.html', status=403)
    request.session['cu20_adulto_mayor_id'] = adulto.pk
    contactos = obtener_contactos_notificacion(request.user, adulto)
    if request.method == 'POST':
        try:
            configuracion = guardar_contacto_notificacion(
                request.user,
                adulto,
                request.POST.get('contacto_id'),
                confirmar=request.POST.get('confirmar_contacto') == 'on',
            )
            messages.success(request, 'La configuración de notificaciones se guardó correctamente.')
            return redirect('configurar_notificaciones', adulto_id=adulto.pk)
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
            configuracion = obtener_configuracion_notificaciones(request.user, adulto)
    else:
        configuracion = obtener_configuracion_notificaciones(request.user, adulto)
    return render(request, 'llamadas/configurar_notificaciones.html', {
        'adulto': adulto,
        'contactos': contactos,
        'configuracion_notificaciones': configuracion,
        'contactos_url': reverse('configuracion_contactos', kwargs={'adulto_id': adulto.pk}),
    })


@require_POST
def api_reportar_estado_permiso(request, adulto_id):
    """Punto de entrada autenticado para los reportes de permisos desde Android."""
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'mensaje': 'Inicia sesión para reportar el estado del dispositivo.'}, status=401)
    adulto = get_object_or_404(User, pk=adulto_id)
    if not verificar_autorizacion_configuracion(request.user, adulto):
        return JsonResponse({'ok': False, 'mensaje': 'No tienes autorización para este dispositivo.'}, status=403)
    try:
        datos = json.loads(request.body.decode('utf-8'))
        if not isinstance(datos, dict):
            return JsonResponse({'ok': False, 'mensaje': 'El cuerpo JSON debe ser un objeto.'}, status=400)
        permiso = actualizar_estado_permiso(
            request.user,
            adulto,
            datos.get('codigo', ''),
            datos.get('estado', ''),
            origen=EstadoPermiso.Origen.DISPOSITIVO_ANDROID,
        )
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'mensaje': 'El cuerpo debe ser JSON válido.'}, status=400)
    except ValidationError as exc:
        return JsonResponse({'ok': False, 'mensaje': '; '.join(exc.messages)}, status=400)
    except PermissionDenied as exc:
        return JsonResponse({'ok': False, 'mensaje': str(exc)}, status=403)
    return JsonResponse({
        'ok': True,
        'codigo': permiso.codigo,
        'estado': permiso.estado,
        'origen': permiso.origen,
        'actualizado_en': permiso.actualizado_en.isoformat(),
    })


@login_required
def configuracion_recurso(request, recurso):
    if recurso == 'ayuda':
        return redirect('ayuda')
    recursos = {
        'sugerencias': ('Sugerencias', 'Envía tus comentarios al equipo que administra esta instalación. No compartas contraseñas, NIP ni códigos de seguridad.'),
        'acerca': ('Acerca de la aplicación', 'Asistente Antifraude Telefónico: ayuda a identificar señales de riesgo y organizar contactos de confianza.'),
    }
    detalle = recursos.get(recurso)
    if detalle is None:
        return render(request, 'llamadas/configuracion_recurso.html', {
            'titulo': 'Recurso no encontrado',
            'descripcion': 'Este recurso no está disponible.',
        }, status=404)
    return render(request, 'llamadas/configuracion_recurso.html', {'titulo': detalle[0], 'descripcion': detalle[1]})


def consultar_ayuda(request, tema=None):
    """Lista temas o presenta instrucciones puntuales; no requiere autenticación."""
    regreso = request.GET.get('volver') or request.META.get('HTTP_REFERER', '')
    if not url_has_allowed_host_and_scheme(
        regreso,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        regreso = reverse('administrar_llamadas')
    if not tema:
        return render(request, 'llamadas/ayuda.html', {
            'temas': TEMAS_AYUDA,
            'volver': regreso,
        })
    contenido = TEMAS_POR_SLUG.get(tema)
    if contenido is None:
        return render(request, 'llamadas/ayuda.html', {
            'temas': TEMAS_AYUDA,
            'volver': regreso,
            'error_tema': 'No encontramos ese tema. Elige uno de la lista.',
        }, status=404)
    return render(request, 'llamadas/ayuda_tema.html', {
        'tema': contenido,
        'temas': TEMAS_AYUDA,
        'volver': regreso,
    })


@require_GET
def ayuda_api(request, tema=None):
    """Entrega el mismo contenido estructurado para una futura app móvil."""
    if tema is None:
        return JsonResponse({'temas': TEMAS_AYUDA}, json_dumps_params={'ensure_ascii': False})
    contenido = TEMAS_POR_SLUG.get(tema)
    if contenido is None:
        return JsonResponse({'error': 'Tema de ayuda no encontrado.'}, status=404, json_dumps_params={'ensure_ascii': False})
    return JsonResponse(contenido, json_dumps_params={'ensure_ascii': False})


def administrar_llamadas(request):
    queryset = Llamada.objects.all()
    estado_filtro = request.GET.get('estado', '')
    busqueda = request.GET.get('q', '').strip()

    if estado_filtro:
        queryset = queryset.filter(estado=estado_filtro)
    if busqueda:
        queryset = queryset.filter(numero_telefonico__icontains=busqueda)

    estadisticas = {
        'total': Llamada.objects.count(),
        'pendientes': Llamada.objects.filter(estado=EstadoLlamada.PENDIENTE_DE_EVALUACION).count(),
        'finalizadas': Llamada.objects.filter(estado=EstadoLlamada.FINALIZADA).count(),
    }

    context = {
        'llamadas': queryset,
        'estadisticas': estadisticas,
        'estado_filtro': estado_filtro,
        'busqueda': busqueda,
        'estados': EstadoLlamada,
    }
    return render(request, 'llamadas/administrar_llamadas.html', context)


def registrar_llamada_view(request):
    relaciones = RelacionFamiliarAdultoMayor.objects.filter(
        familiar=request.user,
        autorizado=True,
    ).select_related('adulto_mayor') if request.user.is_authenticated else RelacionFamiliarAdultoMayor.objects.none()
    if request.method == 'POST':
        form = RegistrarLlamadaForm(request.POST)
        if form.is_valid():
            try:
                adulto = _adulto_mayor_para_llamada(request, request.POST.get('adulto_mayor_id'))
            except PermissionDenied:
                return render(request, 'llamadas/configuracion_denegada.html', status=403)
            if relaciones.exists() and adulto is None:
                form.add_error(None, 'Selecciona el Adulto mayor autorizado para esta llamada.')
            else:
                llamada = registrar_llamada(form.cleaned_data['numero_telefonico'], usuario_protegido=adulto)
                if llamada.estado == EstadoLlamada.PERMITIDA:
                    messages.success(request, 'El número coincide con un contacto de confianza.')
                    return redirect('detalle_llamada', pk=llamada.pk)
                # Presenta la evaluación y luego abre la pantalla de llamada entrante.
                analizar_llamada(llamada)
                generar_resumen_llamada(llamada)
                clasificar_llamada(llamada)
                messages.info(request, f'La evaluación de la llamada {llamada.identificador} está lista.')
                return redirect('alerta_riesgo', pk=llamada.pk)
    else:
        form = RegistrarLlamadaForm()

    return render(request, 'llamadas/registrar_llamada.html', {
        'form': form,
        'adultos_autorizados': [relacion.adulto_mayor for relacion in relaciones],
        'seleccion_multiple': relaciones.count() > 1 and not request.session.get('cu20_adulto_mayor_id'),
    })


def detalle_llamada(request, pk):
    llamada = get_object_or_404(Llamada, pk=pk)
    consultas = llamada.consultas_numero.all()
    transcripciones = llamada.transcripciones.all()
    try:
        analisis = llamada.analisis_llamada
    except AnalisisLlamada.DoesNotExist:
        analisis = None
    resumen = None
    clasificacion_riesgo = getattr(llamada, 'clasificaciones_riesgo', None)
    if clasificacion_riesgo.exists():
        clasificacion_riesgo = clasificacion_riesgo.filter(es_actual=True).first()
    else:
        clasificacion_riesgo = None
    if analisis is not None:
        resumen = getattr(llamada, 'resumen_llamada', None) or generar_resumen_llamada(llamada)
        if clasificacion_riesgo is None:
            clasificacion_riesgo = clasificar_llamada(llamada)
    if transcripciones.exists():
        for transcripcion in transcripciones:
            if transcripcion.texto_transcrito:
                detectar_indicios_fraude(transcripcion)
                if clasificacion_riesgo is None:
                    clasificacion_riesgo = clasificar_llamada(llamada)
    form = AudioLlamadaForm()
    return render(
        request,
        'llamadas/detalle_llamada.html',
        {'llamada': llamada, 'consultas': consultas, 'transcripciones': transcripciones, 'form': form, 'analisis': analisis, 'resumen': resumen, 'clasificacion_riesgo': clasificacion_riesgo},
    )


def realizar_llamada_view(request):
    if request.method == 'POST':
        numero = request.POST.get('numero_telefonico', '').strip()
        if not numero:
            messages.error(request, 'Debe escribir un número telefónico.')
            return redirect('administrar_llamadas')
        try:
            adulto = _adulto_mayor_para_llamada(request, request.POST.get('adulto_mayor_id'))
        except PermissionDenied:
            return render(request, 'llamadas/configuracion_denegada.html', status=403)
        if request.user.is_authenticated and RelacionFamiliarAdultoMayor.objects.filter(familiar=request.user, autorizado=True).count() > 1 and adulto is None:
            return redirect('configuracion_inicio')
        llamada = realizar_llamada(numero, usuario_protegido=adulto)
        # Registra y evalúa la llamada en el flujo normal, sin depender de una simulación.
        analizar_llamada(llamada)
        generar_resumen_llamada(llamada)
        clasificar_llamada(llamada)
        messages.success(request, f'Llamada registrada y evaluada: {llamada.identificador}.')
        return redirect('alerta_riesgo', pk=llamada.pk)
    return redirect('registrar_llamada')


def simulacion_llamada_view(request, pk):
    llamada = get_object_or_404(Llamada, pk=pk)
    sesion = llamada.sesiones_conversacion.first()
    if sesion is None:
        sesion = SesionConversacion.objects.create(llamada=llamada)
        AgenteVoz(sesion).iniciar()
    agente = AgenteVoz(sesion)
    if request.method == 'POST' and sesion.estado != EstadoConversacion.FINALIZADA:
        audio = request.FILES.get('audio')
        if audio and audio.size > 10 * 1024 * 1024:
            messages.error(request, 'La grabación supera 10 MB. Graba una respuesta más corta.')
            return redirect('simulacion_llamada', pk=llamada.pk)
        resultado = agente.procesar_audio(audio) if audio else agente.procesar_respuesta(request.POST.get('respuesta', ''))
        if resultado.get('error'):
            messages.error(request, f"No se entendió el audio: {resultado['error']} Puedes volver a grabar o responder por escrito.")
        if resultado.get('completada'):
            for transcripcion in llamada.transcripciones.all():
                if transcripcion.texto_transcrito:
                    detectar_indicios_fraude(transcripcion)
            analizar_llamada(llamada)
            generar_resumen_llamada(llamada)
            clasificar_llamada(llamada)
            # La llamada queda disponible para la pantalla del destinatario.
            if llamada.usuario_protegido and llamada.usuario_protegido.username == 'adulto_demo_escolar':
                llamada.estado = EstadoLlamada.PENDIENTE_DE_EVALUACION
                llamada.save(update_fields=['estado'])
        return redirect('simulacion_llamada', pk=llamada.pk)
    intervenciones = sesion.intervenciones.select_related('pregunta').all()
    resumen = getattr(llamada, 'resumen_llamada', None)
    if sesion.estado == EstadoConversacion.FINALIZADA:
        for transcripcion in llamada.transcripciones.all():
            if transcripcion.texto_transcrito:
                detectar_indicios_fraude(transcripcion)
        analizar_llamada(llamada)
        resumen = getattr(llamada, 'resumen_llamada', None) or generar_resumen_llamada(llamada)
    return render(request, 'llamadas/simulacion_llamada.html', {
        'llamada': llamada, 'sesion': sesion, 'intervenciones': intervenciones,
        'resumen': resumen,
        'indicadores': llamada.indicadores_fraude.filter(activo=True).order_by('-fecha_detectado'),
    })


def pantalla_movil_view(request):
    return render(request, 'llamadas/pantalla_movil.html')


def _usuario_demo_protegido():
    """Perfil compartido y sin contraseña para las dos pantallas de la demo escolar."""
    adulto, creado = User.objects.get_or_create(username='adulto_demo_escolar')
    if creado:
        adulto.set_unusable_password()
        adulto.save(update_fields=['password'])
    return adulto


def prueba_roles_view(request):
    return render(request, 'llamadas/prueba_roles.html')


def prueba_llamar_view(request):
    form = RegistrarLlamadaForm(request.POST or None)
    form.fields['numero_telefonico'].widget.attrs.update({
        'class': 'w-full min-h-14 rounded-xl border border-slate-300 px-4 text-lg focus:border-brand-primary focus:ring-brand-primary',
        'inputmode': 'tel', 'autocomplete': 'tel',
    })
    if request.method == 'POST' and form.is_valid():
        adulto = _usuario_demo_protegido()
        llamada = registrar_llamada(form.cleaned_data['numero_telefonico'], usuario_protegido=adulto)
        sesion = SesionConversacion.objects.create(llamada=llamada)
        es_seguro = verificar_contacto(llamada.numero_telefonico, usuario_protegido=adulto)
        ultimo_resultado = llamada.consultas_numero.first()
        es_reportado = ultimo_resultado and ultimo_resultado.estado == EstadoConsultaNumero.REPORTADO
        if es_seguro:
            llamada.estado = EstadoLlamada.PERMITIDA
            llamada.resultado_evaluacion = 'Número verificado como contacto seguro; se omitió el filtro de IA.'
            sesion.estado = EstadoConversacion.FINALIZADA
            sesion.fecha_finalizacion = timezone.now()
            llamada.save(update_fields=['estado', 'resultado_evaluacion'])
            sesion.save(update_fields=['estado', 'fecha_finalizacion'])
        elif es_reportado:
            llamada.estado = EstadoLlamada.RECHAZADA
            llamada.resultado_evaluacion = 'Número reportado; llamada terminada automáticamente.'
            sesion.estado = EstadoConversacion.FINALIZADA
            sesion.fecha_finalizacion = timezone.now()
            llamada.save(update_fields=['estado', 'resultado_evaluacion'])
            sesion.save(update_fields=['estado', 'fecha_finalizacion'])
        else:
            llamada.estado = EstadoLlamada.EN_EVALUACION
            llamada.save(update_fields=['estado'])
            AgenteVoz(sesion).iniciar()
        request.session['rol_prueba'] = 'atacante'
        return redirect('simulacion_llamada', pk=llamada.pk)
    return render(request, 'llamadas/prueba_llamar.html', {'form': form})


def prueba_recibir_view(request):
    request.session['rol_prueba'] = 'usuario'
    return redirect('administrar_llamadas')


@require_GET
def estado_llamada_prueba_view(request):
    adulto = _usuario_demo_protegido()
    llamada = Llamada.objects.filter(
        usuario_protegido=adulto,
        estado=EstadoLlamada.PENDIENTE_DE_EVALUACION,
    ).order_by('-fecha_hora_recepcion').first()
    if llamada is None:
        return JsonResponse({'activa': False})
    resumen = getattr(llamada, 'resumen_llamada', None)
    clasificacion = llamada.clasificaciones_riesgo.filter(es_actual=True).first()
    return JsonResponse({
        'activa': True,
        'id': llamada.pk,
        'numero': llamada.numero_telefonico,
        'nivel': clasificacion.nivel if clasificacion else 'AMARILLO',
        'resumen': resumen.texto_resumen if resumen else 'La evaluación terminó; revisa la llamada antes de contestar.',
        'url': reverse('alerta_riesgo', kwargs={'pk': llamada.pk}),
    })


def estado_pantalla_movil_view(request):
    llamada = Llamada.objects.filter(
        estado__in=[EstadoLlamada.PENDIENTE_DE_EVALUACION, EstadoLlamada.EN_EVALUACION]
    ).order_by('-fecha_hora_recepcion').first()
    if llamada is None:
        return JsonResponse({'activa': False})

    return JsonResponse(
        {
            'activa': True,
            'id': llamada.pk,
            'identificador': llamada.identificador,
            'numero_telefonico': llamada.numero_telefonico,
            'estado': llamada.estado,
            'estado_display': llamada.get_estado_display(),
            'alerta_url': reverse('alerta_riesgo', kwargs={'pk': llamada.pk}),
            'analisis_url': reverse('analisis_llamada', kwargs={'pk': llamada.pk}),
            'detalle_url': reverse('detalle_llamada', kwargs={'pk': llamada.pk}),
            'actualizado': timezone.now().isoformat(),
        }
    )


def alerta_riesgo_view(request, pk):
    llamada = get_object_or_404(Llamada, pk=pk)
    if llamada.estado not in {EstadoLlamada.PENDIENTE_DE_EVALUACION, EstadoLlamada.EN_EVALUACION}:
        messages.info(request, 'Esta llamada ya tiene una decisión registrada.')
        return redirect('detalle_llamada', pk=llamada.pk)
    # Reevalúa las respuestas guardadas al abrir la pantalla: las reglas NLP
    # pueden haber mejorado desde que se registró una llamada, y una alerta
    # sensible no debe quedarse mostrando un nivel calculado anteriormente.
    analizar_llamada(llamada)
    resumen = generar_resumen_llamada(llamada)
    clasificacion_riesgo = clasificar_llamada(llamada)
    alerta = mostrar_alerta_riesgo(llamada)
    nivel_por_color = {'VERDE': 'BAJO', 'AMARILLO': 'MEDIO', 'ROJO': 'ALTO'}
    alerta['nivel'] = nivel_por_color.get(clasificacion_riesgo.nivel, 'SIN_EVALUAR')
    alerta['alerta'] = clasificacion_riesgo.nivel in {'AMARILLO', 'ROJO'}
    indicadores = llamada.indicadores_fraude.filter(activo=True).order_by('-fecha_detectado')
    return render(request, 'llamadas/alerta_riesgo.html', {'llamada': llamada, 'alerta': alerta, 'resumen': resumen, 'indicadores': indicadores, 'clasificacion_riesgo': clasificacion_riesgo, 'pantalla_llamada': True})


def responder_alerta_riesgo_view(request, pk):
    llamada = get_object_or_404(Llamada, pk=pk)
    if request.method != 'POST':
        return redirect('alerta_riesgo', pk=llamada.pk)

    accion = request.POST.get('accion', '').strip().lower()
    motivo = request.POST.get('motivo', '').strip()
    if accion == 'aceptar':
        llamada = contestar_llamada_evaluada(llamada, motivo=motivo)
        messages.success(request, 'La llamada fue aceptada y queda permitida.')
    elif accion == 'rechazar':
        llamada = rechazar_llamada_evaluada(llamada, motivo=motivo)
        messages.warning(request, 'La llamada fue rechazada para evitar un riesgo potencial.')
    else:
        messages.error(request, 'Debe elegir una acción válida.')
        return redirect('alerta_riesgo', pk=llamada.pk)
    return redirect('detalle_llamada', pk=llamada.pk)


def analizar_llamada_view(request, pk):
    llamada = get_object_or_404(Llamada, pk=pk)
    analisis = analizar_llamada(llamada)
    resumen = generar_resumen_llamada(llamada)
    for transcripcion in llamada.transcripciones.all():
        if transcripcion.texto_transcrito:
            detectar_indicios_fraude(transcripcion)
    clasificacion_riesgo = clasificar_llamada(llamada)
    return render(request, 'llamadas/analisis_llamada.html', {'analisis': analisis, 'llamada': llamada, 'resumen': resumen, 'clasificacion_riesgo': clasificacion_riesgo})


def decidir_llamada(request, pk):
    analisis = get_object_or_404(AnalisisLlamada, pk=pk)
    if request.method == 'POST':
        decision = request.POST.get('decision', '').upper()
        if decision in {'ACEPTAR', 'RECHAZAR'}:
            analisis.decision_adulto_mayor = decision
            analisis.save(update_fields=['decision_adulto_mayor'])
            messages.success(request, f'Decisión registrada: {analisis.get_decision_adulto_mayor_display()}.')
        else:
            messages.error(request, 'Debe elegir una decisión válida.')
        return redirect('analisis_llamada', pk=analisis.llamada.pk)
    return redirect('analisis_llamada', pk=analisis.llamada.pk)


def procesar_audio_llamada(request, pk):
    llamada = get_object_or_404(Llamada, pk=pk)
    if request.method == 'POST':
        form = AudioLlamadaForm(request.POST, request.FILES)
        if form.is_valid():
            archivo = form.cleaned_data['audio']
            resultado = transcribir_audio(archivo)
            transcripcion = TranscripcionLlamada.objects.create(
                llamada=llamada,
                audio=archivo,
                texto_transcrito=resultado.get('texto', ''),
                fecha_procesamiento=timezone.now(),
                estado=resultado.get('estado', 'ERROR'),
                duracion_audio=float(resultado.get('duracion_audio', 0.0) or 0.0),
                confianza=float(resultado.get('confianza', 0.0) or 0.0),
                orden=form.cleaned_data.get('orden', 1),
                pregunta_asociada=form.cleaned_data.get('pregunta_asociada', ''),
            )
            if resultado.get('estado') == 'COMPLETADO':
                messages.success(request, 'Audio procesado correctamente y transcripción guardada.')
            elif resultado.get('estado') == 'AUDIO_NO_INTELIGIBLE':
                messages.warning(request, 'El audio no contiene voz inteligible y no se inventó una transcripción.')
            else:
                messages.error(request, 'No fue posible procesar el audio: ' + resultado.get('error', 'Error del motor de reconocimiento.'))
            analizar_llamada(llamada)
            generar_resumen_llamada(llamada)
            clasificar_llamada(llamada)
            return redirect('alerta_riesgo', pk=llamada.pk)
    else:
        form = AudioLlamadaForm()

    return render(request, 'llamadas/subir_audio.html', {'form': form, 'llamada': llamada})


def lista_contactos(request):
    usuario = _usuario_propietario_contactos(request)
    queryset = ContactoConfianza.objects.filter(usuario_protegido=usuario)
    busqueda = request.GET.get('q', '').strip()
    if busqueda:
        queryset = queryset.filter(Q(nombre__icontains=busqueda) | Q(numero_telefonico__icontains=busqueda))

    adulto_id = request.session.get('cu20_adulto_mayor_id')
    context = {
        'contactos': queryset,
        'busqueda': busqueda,
        'cantidad_contactos': queryset.count(),
        'cantidad_activos': queryset.filter(activo=True).count(),
        'configuracion_url': reverse('configuracion_aplicacion', kwargs={'adulto_id': adulto_id}) if adulto_id else '',
    }
    return render(request, 'llamadas/contactos_confianza.html', context)


def contacto_crear(request):
    usuario = _usuario_propietario_contactos(request)
    if request.method == 'POST':
        form = ContactoConfianzaForm(request.POST)
        form.usuario_protegido = usuario
        if form.is_valid():
            contacto = form.save(commit=False)
            contacto.usuario_protegido = usuario
            contacto.save()
            _registrar_cambio_contactos(request, usuario)
            messages.success(request, 'Contacto de confianza registrado correctamente.')
            return redirect('lista_contactos')
        messages.error(request, 'No se pudo guardar el contacto. Revise el número o la información ingresada.')
    else:
        form = ContactoConfianzaForm()
        form.usuario_protegido = usuario

    return render(request, 'llamadas/contacto_form.html', {'form': form, 'titulo': 'Agregar contacto'})


def contacto_editar(request, pk):
    usuario = _usuario_propietario_contactos(request)
    contacto = get_object_or_404(ContactoConfianza, pk=pk, usuario_protegido=usuario)
    if request.method == 'POST':
        form = ContactoConfianzaForm(request.POST, instance=contacto)
        form.usuario_protegido = usuario
        if form.is_valid():
            form.save()
            _registrar_cambio_contactos(request, usuario)
            messages.success(request, 'Contacto actualizado correctamente.')
            return redirect('lista_contactos')
        messages.error(request, 'No se pudo actualizar el contacto. Verifique que el número no esté duplicado.')
    else:
        form = ContactoConfianzaForm(instance=contacto)
        form.usuario_protegido = usuario

    return render(request, 'llamadas/contacto_form.html', {'form': form, 'titulo': 'Editar contacto', 'contacto': contacto})


def contacto_eliminar(request, pk):
    usuario = _usuario_propietario_contactos(request)
    contacto = get_object_or_404(ContactoConfianza, pk=pk, usuario_protegido=usuario)
    if request.method == 'POST':
        contacto.delete()
        _registrar_cambio_contactos(request, usuario)
        messages.success(request, 'Contacto eliminado correctamente.')
    return redirect('lista_contactos')


def contacto_toggle(request, pk):
    usuario = _usuario_propietario_contactos(request)
    contacto = get_object_or_404(ContactoConfianza, pk=pk, usuario_protegido=usuario)
    if request.method != 'POST':
        return redirect('lista_contactos')
    contacto.activo = not contacto.activo
    contacto.save()
    _registrar_cambio_contactos(request, usuario)
    estado = 'activado' if contacto.activo else 'desactivado'
    messages.success(request, f'Contacto {estado} correctamente.')
    return redirect('lista_contactos')


def lista_numeros_reportados(request):
    queryset = NumeroReportado.objects.all()
    busqueda = request.GET.get('q', '').strip()
    if busqueda:
        queryset = queryset.filter(
            Q(numero_telefonico__icontains=busqueda)
            | Q(identidad_reportada__icontains=busqueda)
            | Q(tipo_incidente__icontains=busqueda)
        )
    estadisticas = {
        'total': NumeroReportado.objects.count(),
        'activos': NumeroReportado.objects.filter(estado='ACTIVO').count(),
        'reportes': sum(queryset.values_list('cantidad_reportes', flat=True)),
    }
    return render(request, 'llamadas/numeros_reportados.html', {
        'reportados': queryset,
        'busqueda': busqueda,
        'estadisticas': estadisticas,
    })


@never_cache
def numero_reportado_crear(request):
    form = NumeroReportadoForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            registro = form.save()
            messages.success(request, 'Número reportado registrado correctamente.')
            return redirect('lista_numeros_reportados')
    return render(request, 'llamadas/numero_reportado_form.html', {
        'titulo': 'Agregar número reportado',
        'form': form,
    })


@never_cache
def numero_reportado_editar(request, pk):
    registro = get_object_or_404(NumeroReportado, pk=pk)
    form = NumeroReportadoForm(request.POST or None, instance=registro)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Número reportado actualizado correctamente.')
        return redirect('lista_numeros_reportados')
    return render(request, 'llamadas/numero_reportado_form.html', {
        'titulo': 'Editar número reportado',
        'registro': registro,
        'form': form,
    })


def numero_reportado_eliminar(request, pk):
    registro = get_object_or_404(NumeroReportado, pk=pk)
    if request.method == 'POST':
        registro.delete()
        messages.success(request, 'Número reportado eliminado correctamente.')
    return redirect('lista_numeros_reportados')
