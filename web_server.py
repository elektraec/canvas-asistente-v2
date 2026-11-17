"""Optional loopback backend for the static Pages UI; no academic data on GitHub."""
import argparse
import hashlib
import json
import secrets
import tempfile
import time
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from canvas_core import (Canvas, export_assignment, parse_assignment_url,
                         validate_grades, safe_zero_candidates, register_grades)

ROOT = Path(__file__).parent / 'web'
MAX_BODY = 20 * 1024 * 1024


def check_live(data, link, token, include_zeros):
    base, course, aid = parse_assignment_url(link)
    with_canvas = Canvas(base, token)
    try:
        assignment = with_canvas.get_assignment(course, aid)
        subs = with_canvas.get_submissions(course, aid)
        payload = data if data is not None else dict(schema_version=2, canvas_base=base,
                                                    course_id=course, assignment_id=aid, grades=[])
        rows, errors = validate_grades(payload, assignment, subs, base, course, aid)
        zeros, warnings = safe_zero_candidates(subs, assignment) if include_zeros else ([], [])
        return rows, zeros, errors, warnings
    finally:
        with_canvas.close()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        # Do not log URLs, payloads, tokens or student identifiers.
        pass

    def origin_allowed(self):
        return self.headers.get('Origin') in self.server.origins

    def send_data(self, status, data, content_type='application/json'):
        if isinstance(data, dict):
            data = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if self.origin_allowed():
            self.send_header('Access-Control-Allow-Origin', self.headers['Origin'])
            self.send_header('Vary', 'Origin')
        self.end_headers()
        self.wfile.write(data)

    def host_allowed(self):
        return self.headers.get('Host') in self.server.hosts

    def do_OPTIONS(self):
        if not self.host_allowed() or not self.origin_allowed():
            self.send_data(403, {'error': 'Origen no autorizado.'})
            return
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', self.headers['Origin'])
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Bridge-Key')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Vary', 'Origin')
        self.end_headers()

    def do_GET(self):
        if not self.host_allowed():
            self.send_data(403, {'error': 'Host no autorizado.'})
            return
        if self.path == '/api/session':
            # No CORS response: only the UI served by this process can read the key.
            if self.headers.get('Origin') not in (None, *self.server.local_origins):
                self.send_data(403, {'error': 'Acceso local requerido.'})
                return
            self.send_data(200, {'key': self.server.key})
        elif self.path.startswith('/api/'):
            self.send_data(404, {'error': 'Ruta desconocida.'})
        else:
            super().do_GET()

    def do_POST(self):
        if not self.host_allowed() or not self.origin_allowed():
            self.send_data(403, {'error': 'Origen no autorizado.'})
            return
        if not secrets.compare_digest(self.headers.get('X-Bridge-Key', ''), self.server.key):
            self.send_data(403, {'error': 'Clave de sesión local incorrecta.'})
            return
        if not self.server.operation_lock.acquire(blocking=False):
            self.send_data(409, {'error': 'Otra operación está en curso.'})
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= MAX_BODY:
                raise ValueError('Tamaño de solicitud inválido (máximo 20 MB).')
            body = json.loads(self.rfile.read(size))
            link, token = body.get('url', '').strip(), body.get('token', '').strip()
            parse_assignment_url(link)
            if not token:
                raise ValueError('Introduce tu token personal de Canvas.')
            signature = hashlib.sha256((link + '\0' + token).encode()).hexdigest()
            if self.path == '/api/export':
                with tempfile.TemporaryDirectory() as tmp:
                    output = Path(tmp) / 'entregas.zip'
                    export_assignment(link, token, output, lambda _: None)
                    self.send_data(200, output.read_bytes(), 'application/zip')
            elif self.path == '/api/validate':
                self.server.tickets.clear()
                data, include_zeros = body.get('grades'), body.get('include_zeros') is True
                rows, zeros, errors, warnings = check_live(data, link, token, include_zeros)
                ticket = None
                if not errors and (rows or zeros):
                    ticket = secrets.token_urlsafe(32)
                    self.server.tickets[ticket] = dict(signature=signature, data=data,
                        include_zeros=include_zeros, rows=rows, zeros=zeros, expires=time.monotonic()+600)
                self.send_data(200, dict(rows=rows, zeros=zeros, errors=errors, warnings=warnings, ticket=ticket))
            elif self.path == '/api/register':
                if body.get('confirmation') != 'REGISTRAR':
                    raise ValueError('Falta la confirmación docente REGISTRAR.')
                approved = self.server.tickets.pop(body.get('ticket', ''), None)
                if not approved or approved['signature'] != signature or approved['expires'] < time.monotonic():
                    raise ValueError('La validación expiró o cambió la conexión. Valida nuevamente.')
                rows, zeros, errors, _ = check_live(approved['data'], link, token, approved['include_zeros'])
                # Do not add newly eligible zeros after the teacher's review.
                allowed_zeros = {str(s['user_id']) for s in approved['zeros']}
                zeros = [s for s in zeros if str(s['user_id']) in allowed_zeros]
                if errors:
                    raise ValueError('El estado de Canvas cambió: ' + '; '.join(errors))
                results = register_grades(link, token, rows, zeros, lambda _: None)
                self.send_data(200, {'results': results})
            else:
                self.send_data(404, {'error': 'Ruta desconocida.'})
        except Exception as e:
            # Never return request URLs or server errors that may contain a signed URL/token.
            message = str(e) if isinstance(e, ValueError) else 'Falló la conexión con Canvas. Comprueba red, permisos y token; si intentaste registrar, consulta Canvas antes de repetir.'
            self.send_data(400, {'error': message})
        finally:
            self.server.operation_lock.release()


def make_server(port=8765):
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    actual_port = server.server_address[1]
    server.local_origins = {f'http://127.0.0.1:{actual_port}', f'http://localhost:{actual_port}'}
    server.origins = server.local_origins | {'https://elektraec.github.io'}
    server.hosts = {f'127.0.0.1:{actual_port}', f'localhost:{actual_port}'}
    server.key = secrets.token_urlsafe(32)
    server.tickets = {}
    server.operation_lock = threading.Lock()
    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    server = make_server(parser.parse_args().port)
    print(f'Abre http://127.0.0.1:{server.server_port} (conexión automática).', flush=True)
    print(f'Para conectar desde GitHub Pages, clave de sesión: {server.key}', flush=True)
    print('Cierra con Ctrl+C. No se guardan tokens ni evaluaciones.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
