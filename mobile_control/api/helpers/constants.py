# mobile_control/api/helpers/constants.py

"""Constants for mobile authentication API."""

MOBILE_USER_ROLES = ["Mobile User"]
get_mobile_login_ratelimit = 50
get_mobile_otp_ratelimit = 50
ACCESS_TOKEN_TTL_SECONDS = 60 * 60 * 24  # 24 hours
REFRESH_TOKEN_TTL_DAYS = 30
