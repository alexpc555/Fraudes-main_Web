"""Contenido breve y editable de la ayuda CU-22."""


TEMAS_AYUDA = [
    {
        'slug': 'configuracion-inicial',
        'titulo': 'Configuración inicial',
        'resumen': 'La protección básica funciona sin cuenta y sin registrar a un Familiar. Agregar a alguien de confianza para recibir avisos es opcional.',
        'pasos': [
            'Usa la aplicación para evaluar llamadas y administrar números seguros sin crear una cuenta.',
            'Si quieres, agrega un Familiar de confianza desde el inicio. No necesita registrarse ni iniciar sesión.',
            'El contacto se guarda en la agenda de confianza y puede seleccionarse para recibir avisos de riesgo.',
            'Los permisos del teléfono solo los puede conceder Android. Algunas funciones dependen de la futura integración móvil.',
        ],
    },
    {
        'slug': 'permisos',
        'titulo': 'Permisos de la aplicación',
        'resumen': 'Los permisos permiten que la aplicación muestre avisos y se conecte con las funciones del teléfono.',
        'pasos': [
            'Abre los ajustes del teléfono y busca los permisos de la aplicación.',
            'Consulta si cada permiso aparece concedido, denegado o pendiente.',
            'Si está pendiente o denegado, abre los ajustes del teléfono y revisa la aplicación.',
            'La página web no puede conceder permisos. El estado concedido debe reportarlo la aplicación Android.',
        ],
    },
    {
        'slug': 'contactos',
        'titulo': 'Contactos de confianza',
        'resumen': 'Son personas conocidas cuyos números están guardados para que sus llamadas puedan identificarse como conocidas.',
        'pasos': [
            'Abre Contactos de confianza y elige Agregar contacto.',
            'Escribe nombre y número telefónico. El correo es opcional.',
            'Para cambiar un dato, elige Editar junto al contacto.',
            'Para quitarlo de la agenda, elige Eliminar. También puedes desactivarlo temporalmente.',
            'No registres números de personas que no conozcas.',
        ],
    },
    {
        'slug': 'proteccion-llamadas',
        'titulo': 'Cómo funciona la protección de llamadas',
        'resumen': 'La aplicación revisa señales disponibles para ayudarte a decidir qué hacer.',
        'pasos': [
            'Registra la llamada y, cuando sea necesario, carga su audio para obtener una transcripción.',
            'El análisis busca solicitudes de datos, pagos, presión y otras señales de riesgo.',
            'El asistente puede preguntar quién llama, de qué institución y por qué motivo para ayudar a verificar la identidad.',
            'Revisa el resultado y confirma por tu cuenta con un número oficial si tienes dudas.',
        ],
    },
    {
        'slug': 'niveles-riesgo',
        'titulo': 'Niveles de riesgo',
        'resumen': 'El color resume las señales encontradas durante la evaluación.',
        'pasos': [
            'Verde: no se encontraron indicios importantes durante la evaluación. Esto no garantiza que la llamada sea segura.',
            'Amarillo: hay elementos que requieren precaución o no existe información suficiente.',
            'Rojo: se encontraron indicios importantes de posible fraude.',
            'El sistema ayuda a identificar riesgos, pero no garantiza que una llamada sea legítima o fraudulenta.',
        ],
    },
    {
        'slug': 'interpretar-alerta',
        'titulo': 'Cómo interpretar una alerta',
        'resumen': 'Lee el nivel, el motivo y las señales antes de decidir.',
        'pasos': [
            'Observa el color y el nivel que aparece en la parte superior.',
            'Lee el motivo y las señales. La alerta muestra qué elementos activaron la revisión.',
            'No compartas contraseñas, NIP, códigos de verificación ni datos bancarios.',
            'Si dicen ser de un banco o autoridad, cuelga y comunícate usando un número oficial que ya conozcas.',
        ],
    },
    {
        'slug': 'contestar-rechazar',
        'titulo': 'Contestar o rechazar una llamada',
        'resumen': 'La decisión final es tuya; puedes terminar la llamada si no te sientes seguro.',
        'pasos': [
            'Revisa la alerta antes de aceptar o rechazar.',
            'Si rechazas, puedes anotar el motivo para recordarlo después.',
            'Aceptar una llamada no elimina sus señales de riesgo ni confirma que sea legítima.',
            'Ante una amenaza o solicitud urgente de dinero, no continúes la llamada.',
        ],
    },
    {
        'slug': 'notificaciones-familiares',
        'titulo': 'Notificaciones para familiares',
        'resumen': 'Puedes guardar un Familiar de confianza sin crearle una cuenta. La protección principal funciona aunque no configures avisos familiares.',
        'pasos': [
            'Desde el inicio, abre Familiar de confianza (opcional).',
            'Escribe el nombre y teléfono de una persona de confianza. No necesita registrarse ni iniciar sesión.',
            'Guarda los datos para seleccionarla como destinataria de avisos.',
            'Los eventos rojos y las llamadas amarillas o rojas aceptadas quedan registrados.',
            'El aviso push de Android queda pendiente hasta conectar FCM. El correo requiere estar habilitado y configurado.',
        ],
    },
    {
        'slug': 'problemas-frecuentes',
        'titulo': 'Problemas frecuentes',
        'resumen': 'Prueba estos pasos si algo no funciona como esperas.',
        'pasos': [
            'No aparece un contacto: revisa que esté activo y pertenezca al Adulto mayor correcto.',
            'No agregaste un Familiar: la protección de llamadas sigue funcionando; los avisos a otra persona son opcionales.',
            'El permiso sigue pendiente: la web no lo concede; revisa los ajustes de Android y la conexión con la app móvil.',
            'El audio no se transcribe: revisa que el archivo tenga voz clara y esté en un formato compatible.',
            'No llega un aviso: revisa el evento en el sistema. Push requiere FCM; el correo requiere configuración SMTP y habilitación.',
        ],
    },
    {
        'slug': 'soporte-contacto',
        'titulo': 'Soporte y contacto',
        'resumen': 'Esta instalación no tiene un canal externo de soporte configurado.',
        'pasos': [
            'Pide ayuda al Familiar que configuró la aplicación o a la persona que administra esta instalación.',
            'Comparte el identificador de la llamada si necesitas explicar un problema.',
            'No envíes contraseñas, códigos de verificación, NIP ni datos bancarios.',
            'Si crees que hubo fraude, contacta directamente a tu banco o institución usando su número oficial.',
        ],
    },
]

TEMAS_POR_SLUG = {tema['slug']: tema for tema in TEMAS_AYUDA}
