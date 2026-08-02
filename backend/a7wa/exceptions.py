"""DRF error shaping for a panel that lives in an iframe.

The panel is JavaScript talking to a JSON API, never a browser following a
login redirect. DRF answers an unauthenticated session-auth request with 403,
which the panel cannot tell apart from a genuine permission failure — so
"you are not signed in" is normalised to 401 and the panel knows to re-run the
Bitrix handshake.
"""

from rest_framework.exceptions import NotAuthenticated
from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is not None and isinstance(exc, NotAuthenticated):
        response.status_code = 401
    return response
