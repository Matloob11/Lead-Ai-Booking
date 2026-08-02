from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.inbox.serializers import serialize_number

from .models import WaTemplate


def serialize_template(template):
    return {
        "id": template.pk,
        "name": template.name,
        "language": template.language,
        "category": template.category,
        "status": template.status,
        "body_text": template.body_text,
        "variable_count": template.variable_count,
        "components": template.components,
    }


@api_view(["GET"])
def number_list(request):
    return Response([serialize_number(n) for n in request.user.visible_numbers])


@api_view(["GET"])
def number_templates(request, pk):
    # Scoped to visible_numbers so an agent cannot read another team's templates
    # by guessing an id.
    number = get_object_or_404(request.user.visible_numbers, pk=pk)

    templates = WaTemplate.objects.filter(waba_business_id=number.waba_business_id)
    if request.GET.get("all") != "1":
        templates = templates.filter(status=WaTemplate.Status.APPROVED)

    search = request.GET.get("q", "").strip()
    if search:
        templates = templates.filter(name__icontains=search)

    return Response([serialize_template(t) for t in templates])
