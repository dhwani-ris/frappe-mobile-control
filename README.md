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
client. All endpoints expect `POST` requests.

Endpoints:

- `mobile_auth.login` - Login with username/password.
- `mobile_auth.logout` - Logout and revoke refresh tokens.
- `mobile_auth.send_otp` - Send OTP to mobile number.
- `mobile_auth.verify_otp` - Verify OTP and login.
- `mobile_auth.refresh_token` - Refresh access token using refresh token.

Response tokens:

- `access_token` expires in 24 hours.
- `refresh_token` expires in 30 days and is rotated on every refresh.

Client flow:

1. Login or OTP verify to receive `access_token` + `refresh_token`.
2. Use `access_token` as `Authorization: Bearer <access_token>` for API calls.
3. When access token expires, call `mobile_auth.refresh_token` with the
   `refresh_token` to get a new pair.

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
