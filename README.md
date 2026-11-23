# Test-API

A small local API for testing [API Processing Engine](https://github.com/Segue-1/APE). Each endpoint
fails in a predictable way, so you can trigger an error on demand and check that APE corrects it.

## Running

```
python3 api.py
```

Listens on `http://localhost:8081`. No dependencies beyond Python 3.

Send `POST /reset` between tests to clear all state (sessions, instances, counters, maintenance mode).

## Endpoints and how to trigger errors

| Endpoint | Error | How to trigger it | Fix |
|---|---|---|---|
| `GET /secure/profile` | **401**, `X-Error-Code: TOKEN_EXPIRED` | Use a session cookie more times than it allows | `POST /login` for a new cookie |
| `GET /secure/profile` | **401**, `X-Error-Code: NO_SESSION` | Send it with no `Cookie` header | `POST /login` for a cookie |
| `GET /secure/profile` | **503**, `X-Error-Code: MAINTENANCE` | `POST /maintenance` to turn maintenance mode on | `POST /maintenance` again to turn it off |
| `PUT /instances/<id>` | **409**, `X-Expected-Version: N` | Send the wrong `X-Version` header | Resend with the version from `X-Expected-Version` |
| `GET /ratelimited?limit=N` | **429**, `X-RateLimit-Remaining: 0` | The first N calls (default 2) | Keep calling until the limit clears |
| `GET /flaky` | **500**, `X-Error-Code: TRANSIENT` | The first call only | Call it again |
| `POST /form` | **403**, `X-Error-Code: CSRF_INVALID` | Send a missing or old `X-CSRF-Token` | `GET /form` for a fresh token |

Other endpoints:

| Endpoint | Does |
|---|---|
| `POST /login?uses=N` | Issues a session cookie good for N uses (default 2) in `Set-Cookie: session=...` |
| `POST /create` | Creates an instance and returns its `id` |
| `GET /instances`, `GET /instances/<id>` | Lists instances, or shows one |
| `DELETE /instances/<id>` | Deletes an instance |
| `GET/POST/PUT/DELETE /echo` | Returns the exact request it received, to check what APE actually sent |
| `GET /health` | Returns `{"ok": true}` |
| `POST /reset` | Clears all state |

`api_calls.burp` is a Burp project with Repeater tabs for these requests.

## Example APE test cases

### Expired session: log in again

1. `POST /login?uses=1`, copy the token from `Set-Cookie: session=...`.
2. `GET /secure/profile` with `Cookie: session=<token>` twice. The second call returns **401**.
3. In APE:
   - Send the 401 to Error Detection. Error condition: Status Code `401`.
   - Send `POST /login?uses=1` to Corrective Calls. Extract the token from its `Set-Cookie`.
   - Followup: replace the token in `Cookie: session=...` with the extraction.
   - Trigger condition: the 401 error condition → Set 0.
4. Send the profile request again. **Expect 200.**

### Version conflict: fix the request from the error itself

1. `POST /create`, copy the `id`.
2. `PUT /instances/<id>` with `X-Version: 99` returns **409** with `X-Expected-Version: 0`.
3. In APE:
   - Send the 409 to Error Detection. Error condition: Status Code `409`.
   - Extract (Error Detection): the number in `X-Expected-Version`.
   - Followup: replace `99` in `X-Version` with the extraction.
   - Trigger condition: the 409 error condition → Set 0 (no corrective calls needed).
4. Send the PUT again. **Expect 200**, and the version goes up each time.

### Two errors, two fixes

`GET /secure/profile` can fail with 401 (expired cookie) or 503 (maintenance).

- Trigger condition 0: Status Code `401` → Set 0: `POST /login`, extract the token.
- Trigger condition 1: Status Code `503` → Set 1: `POST /maintenance`, then `POST /login`, extract the token.
- Each set's followup replaces the cookie with its own extraction.

Send the profile request with an expired cookie (Set 0 runs), then turn maintenance on and send it
again (Set 1 runs). **Expect 200** both times.

### Three error conditions in one trigger condition

Fire only on an expired cookie, not a missing one:
`Status Code 401` AND `Header X-Error-Code = TOKEN_EXPIRED` AND NOT `Body "no session cookie presented"`.
Removing the `Cookie` header should then return 401 without APE stepping in.
