from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from .files import BODY_MAX, MAX_FILES, NOTE_MAX, OPEN_CAP, classify_upload
from .models import FeedbackAttachment, FeedbackReport
from .serializers import serialize_report


def _visible(user):
    queryset = FeedbackReport.objects.select_related("agent", "solved_by").prefetch_related(
        "attachments"
    )
    if user.has_admin_rights:
        return queryset
    return queryset.filter(agent=user)


def _collect_files(request):
    files = list(request.FILES.getlist("files"))
    if not files:
        single = request.FILES.get("file")
        if single:
            files = [single]
    return files[: MAX_FILES + 1]


@api_view(["GET", "POST"])
@parser_classes([MultiPartParser, FormParser])
def report_list(request):
    if request.method == "GET":
        queryset = _visible(request.user)
        wanted = request.GET.get("status", "")
        if wanted in FeedbackReport.Status.values:
            queryset = queryset.filter(status=wanted)
        rows = [serialize_report(row, request) for row in queryset[:200]]
        return Response(
            {
                "can_solve": bool(request.user.has_admin_rights),
                "results": rows,
            }
        )

    body = str(request.data.get("body", "")).strip()[:BODY_MAX]
    if not body:
        return Response(
            {"detail": "Describe the issue so an admin can act on it."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    open_count = FeedbackReport.objects.filter(
        agent=request.user, status=FeedbackReport.Status.OPEN
    ).count()
    if open_count >= OPEN_CAP:
        return Response(
            {"detail": "You already have several open reports. Wait until an admin closes one."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    files = _collect_files(request)
    if len(files) > MAX_FILES:
        return Response(
            {"detail": f"Attach at most {MAX_FILES} files."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    classified = []
    for file_obj in files:
        kind, mime, error = classify_upload(file_obj)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        classified.append((file_obj, kind, mime))

    report = FeedbackReport.objects.create(agent=request.user, body=body)
    for file_obj, kind, mime in classified:
        name = (getattr(file_obj, "name", "") or "attachment").replace("\\", "/").split("/")[-1]
        FeedbackAttachment.objects.create(
            report=report,
            file=file_obj,
            kind=kind,
            mime_type=(mime or "")[:128],
            file_name=name[:255],
            size_bytes=int(getattr(file_obj, "size", 0) or 0),
        )

    report = _visible(request.user).get(pk=report.pk)
    return Response(serialize_report(report, request), status=status.HTTP_201_CREATED)


@api_view(["POST"])
def report_solve(request, pk):
    if not request.user.has_admin_rights:
        return Response({"detail": "Admins only"}, status=status.HTTP_403_FORBIDDEN)

    report = get_object_or_404(
        FeedbackReport.objects.select_related("agent", "solved_by").prefetch_related("attachments"),
        pk=pk,
    )
    note = str(request.data.get("note", "")).strip()[:NOTE_MAX]
    if report.status != FeedbackReport.Status.SOLVED:
        report.solve(request.user, note)
        report.refresh_from_db()
        report = FeedbackReport.objects.select_related("agent", "solved_by").prefetch_related(
            "attachments"
        ).get(pk=report.pk)
    return Response(serialize_report(report, request))


@api_view(["GET"])
def report_file(request, pk, file_id):
    report = get_object_or_404(_visible(request.user), pk=pk)
    attachment = get_object_or_404(report.attachments.all(), pk=file_id)
    if not attachment.file:
        return Response({"detail": "Attachment is missing"}, status=status.HTTP_404_NOT_FOUND)

    response = FileResponse(
        attachment.file.open("rb"),
        content_type=attachment.mime_type or "application/octet-stream",
        as_attachment=False,
        filename=attachment.file_name or f"attachment-{attachment.pk}",
    )
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    response["X-Content-Type-Options"] = "nosniff"
    return response
