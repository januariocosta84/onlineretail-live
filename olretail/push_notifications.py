"""Push notifications to the TimorMart mobile app via Firebase Cloud
Messaging (FCM) — see mobile/README.md for the app side (Capacitor +
@capacitor/push-notifications) and TLoretail/settings.py for how the
service-account credentials are loaded.

Every call here is best-effort: a push failure (bad token, FCM outage, not
configured yet) never breaks the caller, same as the existing
email-notification fallback in payment_views._notify().
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_firebase_app = None
_firebase_init_attempted = False

# Must match the channel id the Capacitor app creates on Android (see the
# Capacitor-aware script in templates/shared/base.html) — Android routes a
# push through this channel's own sound/vibration/importance settings,
# ignoring whatever is set here, if the ids don't match.
ANDROID_CHANNEL_ID = "default"


def _get_firebase_app():
    """Lazily initialize the Firebase Admin SDK from FIREBASE_SERVICE_ACCOUNT
    (settings.py) — returns None (logging once) if it's unset or invalid,
    so push is a silent no-op until configured rather than an error on
    every request that would otherwise send a notification."""
    global _firebase_app, _firebase_init_attempted
    if _firebase_app is not None:
        return _firebase_app
    if _firebase_init_attempted:
        return None
    _firebase_init_attempted = True

    if not settings.FIREBASE_SERVICE_ACCOUNT:
        return None

    import firebase_admin
    from firebase_admin import credentials

    try:
        cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT)
        _firebase_app = firebase_admin.initialize_app(cred)
    except Exception:
        logger.warning("Failed to initialize Firebase Admin SDK — push notifications disabled", exc_info=True)
        return None
    return _firebase_app


def send_push(user, title, body):
    """Send a push notification to every device `user` has registered
    (olretail.models.DeviceToken). Silently does nothing if Firebase isn't
    configured or the user has no registered devices — callers never need
    to check either condition themselves."""
    app = _get_firebase_app()
    if app is None:
        return

    from .models import DeviceToken

    tokens = list(DeviceToken.objects.filter(user=user).values_list('id', 'token'))
    if not tokens:
        return

    from firebase_admin import messaging

    for token_id, token in tokens:
        message = messaging.Message(
            token=token,
            notification=messaging.Notification(title=title, body=body),
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    channel_id=ANDROID_CHANNEL_ID,
                    sound='default',
                    default_vibrate_timings=True,
                ),
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(aps=messaging.Aps(sound='default')),
            ),
        )
        try:
            messaging.send(message, app=app)
        except messaging.UnregisteredError:
            # App uninstalled, or FCM otherwise invalidated this token —
            # clean it up so future sends stop retrying it.
            DeviceToken.objects.filter(id=token_id).delete()
        except Exception:
            logger.warning(f"Push send failed for device token id={token_id}", exc_info=True)
