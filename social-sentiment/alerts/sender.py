"""
Alert Sender — Telegram primary, Alertmanager secondary.

Telegram:
  - Bot token + chat_id from env
  - Uses requests (sync, fine for alert sending)
  - Formats message as Markdown V2
  - Retries 3× with backoff

Alertmanager:
  - Pushes to /api/v2/alerts endpoint
  - Allows Grafana OnCall / PagerDuty routing from existing Alertmanager
  - Alert resolves itself after 5m (TTL) unless re-fired
"""

from __future__ import annotations

import logging
import time

import requests

from config.settings import (
    ALERTMANAGER_WEBHOOK_URL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)

logger = logging.getLogger(__name__)

SEVERITY_EMOJI = {
    "critical": "🚨",
    "warning": "⚠️",
    "info": "ℹ️",
}


def _escape_md2(text: str) -> str:
    """Escape Telegram MarkdownV2 special chars."""
    for ch in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def _format_telegram(payload: dict) -> str:
    sev = payload.get("severity", "info")
    emoji = SEVERITY_EMOJI.get(sev, "ℹ️")
    brand = payload.get("brand_query", "").upper()
    plat = payload.get("platform", "")
    msg = payload.get("message", "")
    val = payload.get("trigger_value")
    thr = payload.get("threshold")
    fired = payload.get("fired_at", "")

    lines = [
        f"{emoji} *YEET BRAND ALERT*",
        f"*Brand:* {_escape_md2(brand)}",
        f"*Platform:* {_escape_md2(plat)}",
        f"*Severity:* {_escape_md2(sev.upper())}",
        "",
        _escape_md2(msg),
    ]
    if val is not None and thr is not None:
        lines.append(f"*Value:* {val:.3f}  *Threshold:* {thr:.3f}")
    lines.append(f"_Fired: {_escape_md2(fired)}_")
    return "\n".join(lines)


def send_telegram_alert(payload: dict, retries: int = 3) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug("telegram_not_configured")
        return False

    text = _format_telegram(payload)
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    for attempt in range(retries):
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "MarkdownV2",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info(
                    "telegram_alert_sent",
                    extra={"alert_name": payload.get("alert_name")},
                )
                return True
            logger.warning(
                "telegram_send_failed",
                extra={"status": resp.status_code, "body": resp.text[:200]},
            )
        except Exception as exc:
            logger.warning(
                "telegram_send_error", extra={"attempt": attempt, "error": str(exc)}
            )
        time.sleep(2**attempt)

    return False


def send_alertmanager(payload: dict) -> bool:
    """
    Push alert to Alertmanager /api/v2/alerts.
    Alerts auto-resolve after 5m if not re-fired.
    """
    if not ALERTMANAGER_WEBHOOK_URL:
        return False

    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    ends_at = (now + timedelta(minutes=5)).isoformat()

    alert = [
        {
            "labels": {
                "alertname": payload["alert_name"],
                "severity": payload["severity"],
                "platform": payload.get("platform", ""),
                "brand_query": payload.get("brand_query", ""),
                "service": "social-sentiment",
                "env": "production",
            },
            "annotations": {
                "summary": payload["message"],
                "trigger_val": str(payload.get("trigger_value", "")),
                "threshold": str(payload.get("threshold", "")),
            },
            "startsAt": now.isoformat(),
            "endsAt": ends_at,
            "generatorURL": "http://social-sentiment:9465/metrics",
        }
    ]

    try:
        resp = requests.post(ALERTMANAGER_WEBHOOK_URL, json=alert, timeout=5)
        if resp.status_code in (200, 201, 204):
            return True
        logger.warning(
            "alertmanager_push_failed",
            extra={"status": resp.status_code, "body": resp.text[:200]},
        )
    except Exception as exc:
        logger.warning("alertmanager_push_error", extra={"error": str(exc)})

    return False
