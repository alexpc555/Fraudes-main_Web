# Abrir la demo desde otro dispositivo

Para que funcione el micrófono en Chrome del teléfono, usa el enlace HTTPS temporal. El servidor local que se inicia con `run_web_demo.sh` solo acepta conexiones de la misma computadora.

1. Instala `cloudflared` siguiendo la [guía oficial](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/).
2. En la computadora que contiene el proyecto, abre una terminal en la carpeta raíz y ejecuta `./scripts/run_phone_demo.sh`.
3. Espera a que `cloudflared` muestre una URL `https://....trycloudflare.com`.
4. Abre esa URL en Chrome del otro dispositivo y permite el uso del micrófono.
5. Deja la terminal abierta durante la presentación. Al cerrarla con Ctrl+C, el enlace y el servidor se detienen.

El Quick Tunnel crea un enlace público temporal; cualquier persona que tenga ese enlace puede entrar mientras esté activo. Usa solo datos ficticios durante la presentación. El enlace cambia cuando se vuelve a iniciar.
