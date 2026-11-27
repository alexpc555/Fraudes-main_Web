#!/usr/bin/env python3
"""Servidor HTTPS de desarrollo para probar APIs del navegador como el micrófono."""

import argparse
import os
import ssl
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server


class ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cert', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--port', type=int, default=8443)
    args = parser.parse_args()

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fraudes_project.settings')
    from django.core.wsgi import get_wsgi_application

    application = get_wsgi_application()
    server = make_server(
        '127.0.0.1', args.port, application,
        server_class=ThreadedWSGIServer,
        handler_class=WSGIRequestHandler,
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=args.cert, keyfile=args.key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f'Demo HTTPS disponible en https://localhost:{args.port}/')
    print('Deja esta terminal abierta mientras muestras la aplicación. Ctrl+C para cerrar.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nServidor HTTPS detenido.')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
