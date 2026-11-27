# Probar el micrófono desde Android

El navegador solo permite `getUserMedia` en un contexto seguro. `http://localhost` cuenta como seguro; una dirección como `http://192.168.x.x:8000` no.

## Android conectado por USB

1. Activa **Opciones para desarrolladores** y **Depuración USB** en cada teléfono.
2. Conecta ambos teléfonos por USB y acepta el aviso de autorización en cada uno.
3. Detén cualquier servidor Django que ya esté corriendo en el puerto 8000.
4. Desde la raíz del proyecto, ejecuta `./scripts/run_android_mic.sh`. El script configura `adb reverse` para todos los Android autorizados que estén conectados.
5. En Chrome de ambos teléfonos abre `http://localhost:8000/`. En uno elige **Entrar como usuario** y en el otro **Simular llamada como atacante**.
6. Cuando Chrome pregunte, permite el acceso al micrófono en el dispositivo atacante. Pulsa el botón de micrófono para empezar a grabar y vuelve a pulsarlo para enviar la respuesta.

El script configura `adb reverse` en cada dispositivo y ejecuta Django ligado a `127.0.0.1:8000`. Mantén la terminal abierta durante la prueba.

## Desde la computadora

Puedes abrir `http://localhost:8000/` o `http://127.0.0.1:8000/` en el navegador. Para mostrar la aplicación mediante HTTPS, usa `./scripts/run_https_demo.sh` y visita `https://localhost:8443/`. Consulta [https-chrome-demo.md](https-chrome-demo.md) para preparar el certificado local de confianza. No abras el sitio mediante la IP de red local si usa HTTP.

La transcripción del audio se procesa en el servidor con Whisper; la primera respuesta puede tardar más mientras se carga el modelo. El audio WebM/Opus requiere FFmpeg instalado en el servidor.
