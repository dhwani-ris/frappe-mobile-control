### Mobile Control

Mobile Control - Custom Frappe Application

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app mobile_control
```

### Mobile Auth API

These endpoints are exposed as whitelisted methods and are intended for a mobile
client. All endpoints expect `POST` requests and use the `api/v2/method/` route.

Endpoints:

- `mobile_auth.login` - Login with username/password.
- `mobile_auth.logout` - Logout and revoke refresh tokens.
- `mobile_auth.send_login_otp` - Send OTP to mobile number for login.
- `mobile_auth.verify_login_otp` - Verify OTP and complete login.
- `mobile_auth.refresh_token` - Refresh access token using refresh token.
- `mobile_auth.permissions` - Get current user permissions (requires authentication).
- `mobile_auth.get_translations` - Get translation dictionary for one or more languages (requires authentication). By default returns DB translations only; use `all=1` for full (apps + DB). Use `lang=hi,en` for multiple languages.

Response tokens:

- `access_token` expires in 24 hours.
- `refresh_token` expires in 30 days and is rotated on every refresh.

#### Auth response shape (login, verify OTP, refresh token)

Login, `mobile_auth.verify_login_otp`, and `mobile_auth.refresh_token` return a response like:

```json
{
  "message": "Logged In",
  "user": "user@example.com",
  "full_name": "User Name",
  "language": "en",
  "access_token": "...",
  "refresh_token": "...",
  "mobile_form_names": [
    {
      "mobile_doctype": "Mobile Refresh Token",
      "group_name": "",
      "doctype_meta_modifed_at": "2026-02-14 14:40:49.962439",
      "doctype_icon": ""
    }
  ],
  "roles": ["Mobile User", "All", "Desk User"],
  "permissions": [
    {
      "doctype": "Mobile Refresh Token",
      "read": true,
      "write": false,
      "create": true,
      "delete": false,
      "submit": false,
      "cancel": false,
      "amend": false
    }
  ]
}
```

- `language` is the user's language (default `"en"` if blank).
- `roles` is an array of role names.
- `permissions` is an array of objects; each has `doctype` and the flags `read`, `write`, `create`, `delete`, `submit`, `cancel`, `amend`.

Client flow:

1. Login or OTP verify to receive `access_token` + `refresh_token`.
2. Use `access_token` as `Authorization: Bearer <access_token>` for API calls.
3. When access token expires, call `mobile_auth.refresh_token` with the
   `refresh_token` to get a new pair.

User permissions:

- Permissions are automatically included in login, OTP verify, and refresh token responses.
- Permissions include user roles and doctype-level permissions (read, write, create, delete, submit, cancel, amend) for mobile-configured doctypes.
- To refresh permissions without re-authenticating, call `mobile_auth.permissions` endpoint.

Translations:

- Call `GET /api/method/mobile_auth.get_translations?lang=hi` (Bearer token required). Omit `lang` for English (`en`). By default only **DB translations** (Translation doctype) are returned. Add `&all=1` or `&all=true` to get **full translations** (apps CSV/MO + DB). For **multiple languages**, use comma-separated codes: `?lang=hi,en`. Response is always the same shape: `{ "langs": ["hi"], "translations_by_lang": { "hi": { "source text": "translated text", ... } } }` (or multiple keys in `langs` and `translations_by_lang`). Use `translations_by_lang[lang][source] ?? source` for lookup.

#### Request Examples

All requests use:

```
POST {{base_url}}/api/v2/method/<endpoint>
```

Login:

```json
{
  "username": "your.username",
  "password": "your.password"
}
```

Send OTP:

```json
{
  "mobile_no": "+15551234567"
}
```

Verify OTP:

```json
{
  "tmp_id": "TMP_ID_FROM_SEND_OTP",
  "otp": "123456"
}
```

Refresh token:

```json
{
  "refresh_token": "REFRESH_TOKEN"
}
```

Logout:

```
Authorization: Bearer <access_token>
```

Get permissions:

```
GET {{base_url}}/api/method/mobile_auth.permissions
Authorization: Bearer <access_token>
```

Response:
```json
{
  "roles": ["Mobile User", "System Manager"],
  "permissions": [
    {
      "doctype": "Customer",
      "read": true,
      "write": true,
      "create": true,
      "delete": false,
      "submit": true,
      "cancel": false,
      "amend": false
    }
  ]
}
```

#### Bruno Collection

The `API/` directory contains a Bruno collection to try the mobile auth endpoints locally.

**Collection:** `API/bruno.json`

**Requests:**

| File | Description |
|------|-------------|
| `Login with username and password.bru` | POST login with username/password; returns `access_token`, `refresh_token`, `roles`, `permissions`, `language`. |
| `Login with mobile.bru` | POST send OTP to mobile number (`mobile_auth.send_login_otp`). |
| `Login with mobile verify.bru` | POST verify OTP and login (`mobile_auth.verify_login_otp`). |
| `Get Access Token.bru` | POST refresh token to get new `access_token` and `refresh_token`. |
| `Logout.bru` | POST logout (Bearer token required); revokes refresh tokens. |
| `permissions.bru` | GET current user roles and permissions (Bearer token required). |
| `get_translations.bru` | GET translation dictionary; optional `?lang=hi` (Bearer token required). |
| `App Status.bru` | GET app status (enabled, package_name, app_title, version). Guest. |
| `App Configuration.bru` | GET mobile configuration list. Guest. |

**Setup:** Set `base_url` in collection/environment variables. For auth requests, set `username`, `password`, and after login use the returned `access_token` as Bearer token in subsequent requests (or use Bruno’s response scripts to save the token).


### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/mobile_control
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
