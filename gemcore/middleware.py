from django_htmx.http import HttpResponseClientRedirect


class HtmxRedirectMiddleware:
    """Redirects, including expired-session logins, are out of swap targets."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.htmx and response.status_code == 302:
            response = HttpResponseClientRedirect(response["Location"])
        return response
