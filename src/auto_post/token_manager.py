"""Token Management Logic."""

import logging
from datetime import datetime, timedelta

import requests

from .config import InstagramConfig
from .r2_storage import R2Storage

logger = logging.getLogger(__name__)

EXPIRY_THRESHOLD_DAYS = 20  # Refresh if less than 20 days remain


class TokenManager:
    """
    Manages Instagram Access Token lifecycle.
    Persists token in R2 storage.
    """

    def __init__(
        self,
        r2_storage: R2Storage,
        config: InstagramConfig,
        token_file_key: str = "config/instagram_token.json",
        base_url: str = "https://graph.facebook.com",
        api_version: str | None = "v19.0",
        grant_type: str = "fb_exchange_token",
        exchange_param: str = "fb_exchange_token",
        token_endpoint: str = "oauth/access_token",
        include_client_credentials: bool = True,
        fallback_grant_type: str | None = None,
        fallback_exchange_param: str | None = None,
        fallback_token_endpoint: str | None = None,
        fallback_include_client_credentials: bool | None = None,
    ):
        self.r2 = r2_storage
        self.config = config
        self.token_file_key = token_file_key
        self.base_url = base_url
        self.api_version = api_version
        self.grant_type = grant_type
        self.exchange_param = exchange_param
        self.token_endpoint = token_endpoint
        self.include_client_credentials = include_client_credentials
        self.fallback_grant_type = fallback_grant_type
        self.fallback_exchange_param = fallback_exchange_param
        self.fallback_token_endpoint = fallback_token_endpoint
        if fallback_include_client_credentials is None:
            fallback_include_client_credentials = include_client_credentials
        self.fallback_include_client_credentials = fallback_include_client_credentials

    def get_valid_token(self) -> str:
        """
        Get a valid access token.
        1. Check R2 for stored token.
        2. If invalid/missing, use Env token.
        3. Check expiry and refresh if needed.
        4. Return the valid string.
        """
        stored_token, expires_at = self._load_stored_token()
        env_token = self.config.access_token
        token = stored_token or env_token

        # If we don't know expiry (e.g. from env), we should probably fetch it or force refresh?
        # But Graph API debug_token endpoint requires a token to check itself.

        # Let's check expiry via API if not known, or if known check against threshold
        remaining_days = self._check_expiry(token, expires_at)

        if remaining_days is not None and remaining_days < EXPIRY_THRESHOLD_DAYS:
            logger.warning(f"Token expires in {remaining_days:.1f} days. Refreshing...")
            if remaining_days <= 0 and env_token and env_token != token:
                candidates = self._candidate_tokens(env_token, token)
            else:
                candidates = self._candidate_tokens(token, env_token)
            new_token, new_expires_in = self._refresh_with_candidates(candidates)
            if new_token:
                self._save_token(new_token, new_expires_in)
                return new_token
            if remaining_days <= 0 and env_token and env_token != token:
                logger.warning("Stored token expired. Falling back to env token.")
                return env_token
            if remaining_days <= 0:
                logger.error("Token expired and refresh failed. Update access token in env.")
            logger.error("Failed to refresh token. Using old token.")

        return token

    def _check_expiry(self, token: str, known_expires_at: datetime | None) -> float | None:
        """
        Check remaining days.
        If known_expires_at is None, query API to get debug info.
        """
        if known_expires_at:
            delta = known_expires_at - datetime.now()
            return delta.days + (delta.seconds / 86400)

        # Query API for expiry
        # GET https://graph.facebook.com/debug_token?input_token={token}&access_token={token}
        try:
            if self.api_version:
                url = f"{self.base_url}/{self.api_version}/debug_token"
            else:
                url = f"{self.base_url}/debug_token"
            params = {
                "input_token": token,
                "access_token": token # debug_token endpoint uses the token itself for auth usually, or app token
            }
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()

            if "data" in data and "expires_at" in data["data"]:
                # expires_at is unix timestamp
                ts = data["data"]["expires_at"]
                if ts == 0: # Never expires?
                    return 999
                expires_at = datetime.fromtimestamp(ts)

                # Save it so we don't query every time?
                # Actually, if we are here, it means we didn't have it in R2.
                # We should save it to R2 now to avoid API calls next time.
                self._save_token(token, ts - int(datetime.now().timestamp()))

                delta = expires_at - datetime.now()
                return delta.days

            return None
        except Exception as e:
            logger.warning(f"Failed to check token expiry: {e}")
            return None

    def _refresh_token(self, current_token: str) -> tuple[str | None, int | None]:
        """
        Refresh the access token.
        Default (IG Graph) example:
        GET https://graph.facebook.com/v19.0/oauth/access_token?
            grant_type=fb_exchange_token&
            client_id={app-id}&
            client_secret={app-secret}&
            fb_exchange_token={current-token}
        """
        attempts = self._build_refresh_attempts()
        last_error = None
        for attempt in attempts:
            label = attempt["label"]
            logger.info(
                "Token refresh attempt: %s (endpoint=%s grant_type=%s exchange_param=%s client_creds=%s)",
                label,
                attempt["token_endpoint"],
                attempt["grant_type"],
                attempt["exchange_param"],
                attempt["include_client_credentials"],
            )
            data, error_data = self._request_token(
                current_token=current_token,
                grant_type=attempt["grant_type"],
                exchange_param=attempt["exchange_param"],
                token_endpoint=attempt["token_endpoint"],
                include_client_credentials=attempt["include_client_credentials"],
            )
            if data:
                return self._parse_token_response(data, label=f"{label} Response")
            if error_data is not None:
                last_error = error_data
                self._log_attempt_error(label, error_data)

        self._log_refresh_error(last_error)
        return None, None

    def _build_refresh_attempts(self) -> list[dict]:
        attempts: list[dict] = []

        def add_attempt(label: str, grant_type: str, exchange_param: str, token_endpoint: str, include_client_credentials: bool):
            key = (grant_type, exchange_param, token_endpoint, include_client_credentials)
            for existing in attempts:
                if existing["key"] == key:
                    return
            attempts.append({
                "label": label,
                "grant_type": grant_type,
                "exchange_param": exchange_param,
                "token_endpoint": token_endpoint,
                "include_client_credentials": include_client_credentials,
                "key": key,
            })

        add_attempt(
            "primary",
            self.grant_type,
            self.exchange_param,
            self.token_endpoint,
            self.include_client_credentials,
        )

        if self.fallback_grant_type and self.fallback_exchange_param and self.fallback_token_endpoint:
            add_attempt(
                "fallback",
                self.fallback_grant_type,
                self.fallback_exchange_param,
                self.fallback_token_endpoint,
                self.fallback_include_client_credentials,
            )

            if self.fallback_grant_type == "th_exchange_token":
                for alt_param in ("exchange_token", "access_token"):
                    if alt_param != self.fallback_exchange_param:
                        add_attempt(
                            f"fallback-param-{alt_param}",
                            self.fallback_grant_type,
                            alt_param,
                            self.fallback_token_endpoint,
                            self.fallback_include_client_credentials,
                        )
                if self.fallback_token_endpoint != "access_token":
                    add_attempt(
                        "fallback-endpoint-access_token",
                        self.fallback_grant_type,
                        self.fallback_exchange_param,
                        "access_token",
                        self.fallback_include_client_credentials,
                    )

        return attempts

    def _request_token(
        self,
        current_token: str,
        grant_type: str,
        exchange_param: str,
        token_endpoint: str,
        include_client_credentials: bool,
    ) -> tuple[dict | None, dict | None]:
        try:
            if include_client_credentials and (not self.config.app_id or not self.config.app_secret):
                logger.error("Token refresh missing app credentials (app_id/app_secret).")
            if self.api_version:
                url = f"{self.base_url}/{self.api_version}/{token_endpoint}"
            else:
                url = f"{self.base_url}/{token_endpoint}"
            params = {
                "grant_type": grant_type,
                exchange_param: current_token
            }
            if include_client_credentials:
                params["client_id"] = self.config.app_id
                params["client_secret"] = self.config.app_secret

            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json(), None
        except Exception as e:
            error_data = None
            status = None
            if hasattr(e, "response") and e.response is not None:
                status = e.response.status_code
                try:
                    error_data = e.response.json()
                except ValueError:
                    error_data = {"raw": e.response.text}
            if status is not None:
                logger.error("Token refresh failed: HTTP %s", status)
            else:
                logger.error("Token refresh failed: %s", type(e).__name__)
            return None, error_data

    def _parse_token_response(self, data: dict, label: str) -> tuple[str | None, int | None]:
        new_token = data.get("access_token")
        expires_in = data.get("expires_in")  # Seconds

        masked = dict(data)
        if "access_token" in masked and isinstance(masked["access_token"], str):
            masked["access_token"] = self._mask_token(masked["access_token"])
        logger.info("%s: %s", label, masked)

        if new_token and expires_in is None:
            logger.warning("expires_in not found in response. Defaulting to 60 days.")
            expires_in = 5184000  # 60 days

        return new_token, expires_in

    def _log_attempt_error(self, label: str, error_data: dict | None):
        if not error_data:
            return
        logger.error("Token refresh attempt error (%s): %s", label, self._format_error_json(error_data))
        if isinstance(error_data, dict) and "error" in error_data:
            err = error_data["error"]
            user_title = err.get("error_user_title")
            user_msg = err.get("error_user_msg")
            if user_title or user_msg:
                logger.error("Token refresh attempt user message (%s): %s %s", label, user_title or "", user_msg or "")

    def _log_refresh_error(self, error_data: dict | None):
        if not error_data:
            return
        logger.error("Error Response: %s", self._format_error_json(error_data))
        if isinstance(error_data, dict) and "error" in error_data:
            err = error_data["error"]
            user_title = err.get("error_user_title")
            user_msg = err.get("error_user_msg")
            if user_title or user_msg:
                logger.error("Error User Message: %s %s", user_title or "", user_msg or "")

    def _format_error_json(self, error_data: dict) -> str:
        import json
        return json.dumps(error_data, ensure_ascii=False)

    def _mask_token(self, token: str) -> str:
        if len(token) <= 12:
            return f"{token[:3]}...{token[-3:]}"
        return f"{token[:6]}...{token[-4:]}"

    def _load_stored_token(self) -> tuple[str | None, datetime | None]:
        """Load token and expiry from R2 storage."""
        stored_data = self.r2.get_json(self.token_file_key)
        if not stored_data:
            return None, None

        logger.info("Loaded token from R2 storage")
        expires_at = None
        expires_at_str = stored_data.get("expires_at")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str)
        return stored_data.get("access_token"), expires_at

    def _candidate_tokens(self, primary: str | None, fallback: str | None) -> list[str]:
        """Build a list of unique, non-empty token candidates."""
        tokens: list[str] = []
        for token in (primary, fallback):
            if token and token not in tokens:
                tokens.append(token)
        return tokens

    def _refresh_with_candidates(self, candidates: list[str]) -> tuple[str | None, int | None]:
        """Attempt refresh with multiple candidate tokens."""
        for candidate in candidates:
            new_token, expires_in = self._refresh_token(candidate)
            if new_token:
                return new_token, expires_in
        return None, None

    def _save_token(self, token: str, expires_in_seconds: int):
        """Save token and calculated expiry to R2."""
        expires_at = datetime.now() + timedelta(seconds=expires_in_seconds)
        data = {
            "access_token": token,
            "expires_at": expires_at.isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        self.r2.put_json(data, self.token_file_key)
        logger.info(f"Token saved to R2. Expires at: {expires_at}")

    def force_refresh(self) -> str | None:
        """Force a token refresh and save to R2."""
        stored_token, expires_at = self._load_stored_token()
        env_token = self.config.access_token
        if expires_at and expires_at <= datetime.now() and env_token and env_token != stored_token:
            candidates = self._candidate_tokens(env_token, stored_token)
        else:
            candidates = self._candidate_tokens(stored_token, env_token)
        new_token, expires_in = self._refresh_with_candidates(candidates)
        if new_token:
            self._save_token(new_token, expires_in)
            return new_token
        return None
