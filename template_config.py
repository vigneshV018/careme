from starlette.templating import Jinja2Templates
from starlette.responses import HTMLResponse
from config import DEMO_MODE, APP_NAME, APP_TAGLINE
from services.csrf import get_or_create_csrf_token
from services.timezone import format_kolkata, to_kolkata

class UniversalTemplates(Jinja2Templates):
    def TemplateResponse(self, *args, **kwargs):
        status_code = kwargs.pop("status_code", 200)
        headers = kwargs.pop("headers", None)
        media_type = kwargs.pop("media_type", None)
        background = kwargs.pop("background", None)

        request = kwargs.pop("request", None)
        name = kwargs.pop("name", None)
        context = kwargs.pop("context", None)

        if len(args) >= 1:
            if isinstance(args[0], str):
                name = args[0]
            else:
                request = args[0]

        if len(args) >= 2:
            if isinstance(args[1], dict):
                context = args[1]
            elif isinstance(args[1], str):
                name = args[1]

        if len(args) >= 3 and isinstance(args[2], dict):
            context = args[2]

        if context is None:
            context = {}

        if request is None and isinstance(context, dict):
            request = context.get("request")
        elif request is not None and "request" not in context:
            context["request"] = request

        # Ensure demo_mode is always present in template context
        if "demo_mode" not in context:
            context["demo_mode"] = DEMO_MODE

        tpl = self.get_template(name)
        content = tpl.render(context)
        return HTMLResponse(
            content=content,
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            background=background
        )

templates = UniversalTemplates(directory="templates")
templates.env.globals["demo_mode"] = DEMO_MODE
templates.env.globals["app_name"] = APP_NAME
templates.env.globals["app_tagline"] = APP_TAGLINE
templates.env.globals["csrf_token"] = get_or_create_csrf_token

# Jinja2 Asia/Kolkata formatting filters
templates.env.filters["kolkata_time"] = lambda dt: format_kolkata(dt, "%I:%M %p")
templates.env.filters["kolkata_date"] = lambda dt: format_kolkata(dt, "%d %b %Y")
templates.env.filters["kolkata_datetime"] = lambda dt: format_kolkata(dt, "%d %b %Y, %I:%M %p")
