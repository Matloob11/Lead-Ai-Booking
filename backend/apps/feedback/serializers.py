from django.urls import reverse


def _iso(value):
    return value.isoformat() if value else None


def _agent(agent):
    if agent is None:
        return None
    return {
        "id": agent.pk,
        "display_name": agent.display_name or agent.get_username(),
    }


def serialize_attachment(attachment, request=None):
    url = reverse("feedback:file", args=[attachment.report_id, attachment.pk])
    if request is not None:
        url = request.build_absolute_uri(url)
    return {
        "id": attachment.pk,
        "kind": attachment.kind,
        "file_name": attachment.file_name,
        "mime": attachment.mime_type,
        "size": attachment.size_bytes,
        "url": url,
    }


def serialize_report(report, request=None):
    attachments = list(report.attachments.all())
    return {
        "id": report.pk,
        "body": report.body,
        "status": report.status,
        "created_at": _iso(report.created_at),
        "solved_at": _iso(report.solved_at),
        "admin_note": report.admin_note or "",
        "agent": _agent(report.agent),
        "solved_by": _agent(report.solved_by),
        "attachments": [serialize_attachment(row, request) for row in attachments],
    }
