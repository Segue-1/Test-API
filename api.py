from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import json
import threading
import time
import urllib.parse
import uuid


# Guards the module level state below. ThreadingHTTPServer serves each connection on its own thread,
# so counters and sessions would otherwise race and make test results non-deterministic.
LOCK = threading.RLock()

CRLF = "\r\n"


class GenericResource:
    def __init__(self):
        self.id = str(uuid.uuid4())
        self.version = 0
        self.state = "Stopped"
        self.title = "Default Title"
        self.description = "Default Description"
        self.processing_results = 0

    def get(self):
        print("Version: " + str(self.version))
        print("State: " + self.state)
        print("Title: " + self.title)
        print("Description " + self.description)
        print("Processing results (ignore if 0): " + str(self.processing_results))

    def modify(self, title_input, description_input):
        # Logically could be updated
        if self.title != title_input and self.description != description_input:
            self.title = title_input
            self.description = description_input
            self.version += 1
        else:
            return

    def dowork(self, n):
        self.state = "Processing"
        self.processing_results = self.processing(n)
        self.state = "Complete"

    # 44 takes about 1 minutes 45 seconds to complete. 31 is very quick / near instant.
    def processing(self, n):
        if n >= 45:
            print("Number too large, not enough processing power. Pass an int less than 45.")
            return
        elif n <= 1:
            return n
        else:
            return self.processing(n - 1) + self.processing(n - 2)

    def to_dict(self):
        return {
            "id": self.id,
            "version": self.version,
            "state": self.state,
            "title": self.title,
            "description": self.description,
            "processing_results:": self.processing_results
        }


class Session:
    """
    A cookie session that expires on a use count as well as on a wall clock TTL.

    The use count is what tests rely on: it expires deterministically on the Nth request rather than
    after an unpredictable delay. The TTL is there so the behaviour is realistic and so a slow run
    still sees an expiry, but it defaults long enough not to make tests flaky.
    """

    def __init__(self, uses_allowed=2, ttl_seconds=60):
        self.token = uuid.uuid4().hex
        self.uses_allowed = uses_allowed
        self.uses = 0
        self.created = time.time()
        self.ttl_seconds = ttl_seconds

    def expiry_reason(self):
        if self.uses >= self.uses_allowed:
            return "uses"
        if time.time() - self.created > self.ttl_seconds:
            return "ttl"
        return None

    def consume(self):
        self.uses += 1


def reset_state():
    with LOCK:
        instances.clear()
        sessions.clear()
        counters.clear()
        csrf_tokens.clear()
        flags["maintenance"] = False


def bump(name):
    """Increments a named counter and returns the value BEFORE the increment."""
    with LOCK:
        current = counters.get(name, 0)
        counters[name] = current + 1
        return current


def parse_path(raw_path):
    parsed = urllib.parse.urlparse(raw_path)
    return parsed.path, urllib.parse.parse_qs(parsed.query)


def query_int(query, name, default):
    try:
        return int(query.get(name, [default])[0])
    except (TypeError, ValueError):
        return default


class HTTPRequestHandler(BaseHTTPRequestHandler):

    # ------------------------------------------------------------------ helpers

    def _json(self, status, payload, headers=None):
        body = json.dumps(payload).encode('utf-8')

        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        for name, value in (headers or []):
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _body_bytes(self):
        length = self.headers.get('Content-Length')
        if not length:
            return b''
        try:
            return self.rfile.read(int(length))
        except (TypeError, ValueError):
            return b''

    def _cookies(self):
        """Parses the Cookie header into a dict. Returns {} when absent."""
        raw = self.headers.get('Cookie')
        if not raw:
            return {}

        jar = {}
        for part in raw.split(';'):
            if '=' in part:
                name, value = part.split('=', 1)
                jar[name.strip()] = value.strip()
        return jar

    def _session(self):
        """
        Resolves the request's session cookie.

        Returns (session, reason) where reason is None when the session is usable, or one of
        'missing' / 'unknown' / 'uses' / 'ttl' describing why it is not.
        """
        token = self._cookies().get('session')
        if not token:
            return None, 'missing'

        with LOCK:
            session = sessions.get(token)
            if session is None:
                return None, 'unknown'

            reason = session.expiry_reason()
            if reason:
                return session, reason

            session.consume()
            return session, None

    def _unauthorized(self, reason):
        """
        The 401 an expired or missing session gets.

        Deliberately carries three independently matchable signals, so a trigger condition can key on
        the status code, on text in the body, or on a header value, and so several error conditions can
        be combined with AND / OR / negation against one response:

            status 401
            body contains "session token expired" (or "no session")
            X-Error-Code: TOKEN_EXPIRED (or NO_SESSION)
        """
        if reason in ('uses', 'ttl'):
            code = 'TOKEN_EXPIRED'
            message = 'session token expired'
        else:
            code = 'NO_SESSION'
            message = 'no session cookie presented'

        self._json(401,
                   {"error": message, "reason": reason},
                   [('X-Error-Code', code), ('WWW-Authenticate', 'Cookie realm="ape"')])

    # ------------------------------------------------------------------ POST

    def do_POST(self):
        path, query = parse_path(self.path)

        if path == '/create':
            try:
                with LOCK:
                    new_instance = GenericResource()
                    instances[new_instance.id] = new_instance

                self._json(201, {
                    "Message": "GenericResource created!",
                    "id": str(new_instance.id)
                })
            except json.JSONDecodeError:
                self.send_error(400, "Invalid JSON")
            except Exception as e:
                self.send_error(500, f"Internal Server Error: " + str(e))

        elif path == '/reset':
            reset_state()
            self._json(200, {"message": "state cleared"})

        # Issues a session cookie. /login?uses=1 makes it expire on the very next use, which is the
        # fast expiry the corrective-call scenarios are built around.
        elif path == '/login':
            uses = query_int(query, 'uses', 2)
            ttl = query_int(query, 'ttl', 60)

            with LOCK:
                session = Session(uses_allowed=uses, ttl_seconds=ttl)
                sessions[session.token] = session

            self._json(200,
                       {"message": "logged in", "session": session.token, "uses_allowed": uses},
                       [('Set-Cookie', 'session=' + session.token + '; Path=/; HttpOnly')])

        # Requires the CSRF token most recently handed out by GET /form, echoed in X-CSRF-Token.
        elif path == '/form':
            self._body_bytes()
            supplied = self.headers.get('X-CSRF-Token')

            with LOCK:
                expected = csrf_tokens.get('current')

            if expected is None or supplied != expected:
                self._json(403,
                           {"error": "csrf token invalid", "supplied": supplied},
                           [('X-Error-Code', 'CSRF_INVALID')])
                return

            self._json(200, {"message": "form accepted", "csrf": supplied})

        elif path == '/maintenance':
            self._body_bytes()
            with LOCK:
                flags["maintenance"] = not flags["maintenance"]
                state = flags["maintenance"]
            self._json(200, {"maintenance": state})

        elif path == '/echo':
            self._echo()

        else:
            self.send_error(404, "Path not found")

    # ------------------------------------------------------------------ GET

    def do_GET(self):
        path, query = parse_path(self.path)

        if path == '/health':
            self._json(200, {"ok": True})

        # List
        elif path == '/instances':
            with LOCK:
                if instances:
                    response = {
                        "instances": [instance.to_dict() for instance in instances.values()],
                        "count": len(instances)
                    }
                else:
                    response = {"instances": "None", "count": 0}
            self._json(200, response)

        # Get
        elif path.startswith('/instances/'):
            parsed_id = path[len('/instances/'):]

            try:
                with LOCK:
                    instance = instances.get(parsed_id)

                if instance is not None:
                    self._json(200, {"instance": instance.to_dict()})
                else:
                    self.send_error(404, f"Instance with ID {parsed_id} not found")
            except ValueError:
                self.send_error(400, "Invalid instance ID format")
            except Exception as e:
                self.send_error(500, f"Internal Server Error: " + str(e))

        # Cookie protected. Expires on the use count set at login.
        elif path in ('/secure/profile', '/secure/data'):
            with LOCK:
                if flags["maintenance"]:
                    self._json(503,
                               {"error": "service in maintenance"},
                               [('Retry-After', '1'), ('X-Error-Code', 'MAINTENANCE')])
                    return

            session, reason = self._session()
            if reason:
                self._unauthorized(reason)
                return

            if path == '/secure/profile':
                self._json(200, {
                    "profile": {"user": "ape", "role": "tester"},
                    "uses": session.uses,
                    "uses_allowed": session.uses_allowed
                })
            else:
                self._json(200, {"data": "secret-payload", "uses": session.uses})

        # 429 for the first N calls (default 2), then 200. Deterministic via a counter.
        elif path == '/ratelimited':
            limit = query_int(query, 'limit', 2)
            seen = bump('ratelimited')

            if seen < limit:
                self._json(429,
                           {"error": "rate limit exceeded", "attempt": seen + 1},
                           [('Retry-After', '1'), ('X-RateLimit-Remaining', '0'),
                            ('X-Error-Code', 'RATE_LIMITED')])
            else:
                self._json(200,
                           {"message": "ok", "attempt": seen + 1},
                           [('X-RateLimit-Remaining', '59')])

        # 500 on the first call, 200 afterwards. A transient failure worth one retry.
        elif path == '/flaky':
            seen = bump('flaky')

            if seen == 0:
                self._json(500,
                           {"error": "internal error", "attempt": 1},
                           [('X-Error-Code', 'TRANSIENT')])
            else:
                self._json(200, {"message": "recovered", "attempt": seen + 1})

        # Hands out a CSRF token that POST /form then demands back.
        elif path == '/form':
            token = uuid.uuid4().hex
            with LOCK:
                csrf_tokens['current'] = token
            self._json(200, {"csrf": token, "message": "submit this token in X-CSRF-Token"})

        elif path == '/echo':
            self._echo()

        else:
            self.send_error(404, "Path not found")

    # ------------------------------------------------------------------ PUT

    def do_PUT(self):
        path, query = parse_path(self.path)

        # Optimistic concurrency: the caller must present the version it thinks it is updating.
        # A mismatch is a 409 that names the version it should have used, so a corrective call can
        # read the right one out of the error response itself.
        if path.startswith('/instances/'):
            parsed_id = path[len('/instances/'):]
            body = self._body_bytes()

            with LOCK:
                instance = instances.get(parsed_id)

            if instance is None:
                self.send_error(404, f"Instance with ID {parsed_id} not found")
                return

            supplied = self.headers.get('X-Version')

            if supplied is None or supplied != str(instance.version):
                self._json(409,
                           {"error": "version conflict",
                            "supplied": supplied,
                            "expected": instance.version},
                           [('X-Expected-Version', str(instance.version)),
                            ('X-Error-Code', 'VERSION_CONFLICT')])
                return

            try:
                payload = json.loads(body) if body else {}
            except json.JSONDecodeError:
                self.send_error(400, "Invalid JSON")
                return

            with LOCK:
                instance.title = payload.get('title', instance.title)
                instance.description = payload.get('description', instance.description)
                instance.version += 1
                new_version = instance.version

            self._json(200, {"message": "updated", "version": new_version})

        elif path == '/echo':
            self._echo()

        else:
            self.send_error(404, "Path not found")

    # ------------------------------------------------------------------ DELETE

    def do_DELETE(self):
        path, query = parse_path(self.path)

        if path.startswith('/instances/'):
            parsed_id = path[len('/instances/'):]

            try:
                with LOCK:
                    present = parsed_id in instances
                    if present:
                        del instances[parsed_id]

                if present:
                    self._json(200, {"message": "Instance " + parsed_id + " has been deleted!"})
                else:
                    self.send_error(404, f"Instance with ID {parsed_id} not found")
            except Exception as e:
                self.send_error(500, f"Internal Server Error: " + str(e))

        elif path == '/echo':
            self._echo()

        else:
            self.send_error(404, "Path not found")

    # ------------------------------------------------------------------ echo

    def _echo(self):
        """
        Reflects the request back as text: request line, headers, then body.

        This is the only endpoint that can show what bytes actually arrived, which is what proves a
        rebuilt request was framed correctly rather than merely accepted. A wrong Content-Length shows
        up here as a truncated or missing body instead of a silent pass.
        """
        body = self._body_bytes()

        reflected = self.requestline + CRLF
        for name, value in self.headers.items():
            reflected += name + ": " + value + CRLF
        reflected += CRLF
        reflected += body.decode('utf-8', errors='replace')

        payload = reflected.encode('utf-8')

        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('X-Echo-Body-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(payload)

    # Quieter logs; the harness output is the interesting part.
    def log_message(self, fmt, *args):
        return


instances = {}
sessions = {}
counters = {}
csrf_tokens = {}
flags = {"maintenance": False}

if __name__ == '__main__':
    server_address = ('', 8081)
    httpd = ThreadingHTTPServer(server_address, HTTPRequestHandler)
    print("Server running on http://localhost:8081")
    print()
    print("Original endpoints:")
    print("  POST   /create                 create an instance")
    print("  GET    /instances              list instances")
    print("  GET    /instances/<id>         get one instance")
    print("  DELETE /instances/<id>         delete one instance")
    print()
    print("Added for APE testing:")
    print("  GET    /health                 liveness")
    print("  POST   /reset                  clear all state")
    print("  POST   /login[?uses=N&ttl=S]   issue a session cookie (default 2 uses)")
    print("  GET    /secure/profile         401 TOKEN_EXPIRED once the session is used up")
    print("  GET    /secure/data            same auth, different payload")
    print("  GET    /ratelimited[?limit=N]  429 for the first N calls, then 200")
    print("  GET    /flaky                  500 on the first call, then 200")
    print("  GET    /form                   hands out a CSRF token")
    print("  POST   /form                   403 unless X-CSRF-Token matches")
    print("  PUT    /instances/<id>         409 unless X-Version matches")
    print("  POST   /maintenance            toggles 503 on /secure/*")
    print("  ANY    /echo                   reflects the request back as text")
    httpd.serve_forever()
