"""The shops media library in the Lead AI screen (board T30; shop_media.py holds the rules), and the
studio and one-bedroom photo sets (batch 2e slice E, board T96; unit_media.py holds the rules).

GET    /api/leadai/shop-media/                 every type's files, in sending order (every agent)
POST   /api/leadai/shop-media/                 add a file: multipart "shop" (type_1..type_3, office) and "file"
POST   /api/leadai/shop-media/<id>/replace/    the same place in the order, another file
DELETE /api/leadai/shop-media/<id>/            take a file out
POST   /api/leadai/shop-media/reorder/         {"shop": "type_1", "ids": [3, 1, 2]}
GET    /api/leadai/shop-media/<id>/file/       the file itself (every agent: it is what customers get)
GET    /api/leadai/unit-media/                 the studio and one-bedroom sets by unit (every agent; read only)
GET    /api/leadai/unit-media/<id>/file/       one set photo (every agent: it is what customers get)

Changes need a panel admin, the gate of the AI settings (views._can_edit). A
refused file answers 400 {"detail": why}, in words an admin can act on. The sets
change only by their import (leadai_media_import), never here: a set's photos
are not the shop library's, so its routes never take them either.
"""

from __future__ import annotations

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from . import shop_media, unit_media
from .assistant import shops
from .models import LeadAiSettings, LeadAiShopMedia
from .views import _can_edit

UPLOAD_MAX = shop_media.VIDEO_MAX + 1


def _shop_label(shop: str, facts) -> str:
    if shop == shop_media.Shop.OFFICE:
        return "Office"
    found = shops.type_by_key(shop, facts)
    return found.name if found is not None else shop_media.Shop(shop).label


def _row(row: LeadAiShopMedia) -> dict:
    by = row.uploaded_by
    return {
        "id": row.pk,
        "shop": row.shop,
        "kind": row.kind,
        "file_name": row.file_name,
        "mime_type": row.mime_type,
        "size_bytes": row.size_bytes,
        "order": row.order,
        "url": f"/api/leadai/shop-media/{row.pk}/file/",
        "uploaded_by": (by.display_name or by.get_username()) if by is not None else "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def serialize_library(user) -> dict:
    facts = LeadAiSettings.load().shops_facts
    groups = []
    for shop in shop_media.SHOP_LIBRARY:
        rows = shop_media.rows_for(shop)
        office = shop == shop_media.Shop.OFFICE
        groups.append(
            {
                "shop": shop,
                "label": _shop_label(shop, facts),
                "items": [_row(row) for row in rows],
                "limits": {"videos": 0 if office else shop_media.VIDEOS_PER_TYPE, "photos": shop_media.OFFICE_PHOTOS if office else shop_media.PHOTOS_PER_TYPE},
            }
        )
    return {
        "can_edit": _can_edit(user),
        "limits": {"video_mb": shop_media.VIDEO_MAX // shop_media.MB, "photo_mb": shop_media.PHOTO_MAX // shop_media.MB},
        "shops": groups,
    }


def _forbidden():
    return Response({"detail": "Only a panel admin can change the shop media."}, status=status.HTTP_403_FORBIDDEN)


def _read_upload(request):
    """(name, bytes) of the uploaded "file", or (None, why)."""
    upload = request.FILES.get("file")
    if upload is None:
        return None, "Choose a file."
    if getattr(upload, "size", 0) and upload.size > UPLOAD_MAX:
        return None, f"{shop_media.clean_name(upload.name)}: the file is larger than 16 MB."
    data = upload.read(UPLOAD_MAX + 1)
    return (upload.name or "file", data), ""


@api_view(["GET", "POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def library(request):
    if request.method == "GET":
        return Response(serialize_library(request.user))
    if not _can_edit(request.user):
        return _forbidden()
    shop = str(request.data.get("shop") or "").strip()
    upload, error = _read_upload(request)
    if error:
        return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
    name, data = upload
    try:
        _, created = shop_media.add(shop, name, data, uploaded_by=request.user)
    except shop_media.MediaRejected as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    payload = serialize_library(request.user)
    payload["created"] = created
    return Response(payload, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(["DELETE"])
def item(request, pk):
    if not _can_edit(request.user):
        return _forbidden()
    row = get_object_or_404(LeadAiShopMedia, pk=pk, shop__in=shop_media.SHOP_LIBRARY)
    shop_media.delete(row)
    return Response(serialize_library(request.user))


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def replace(request, pk):
    if not _can_edit(request.user):
        return _forbidden()
    row = get_object_or_404(LeadAiShopMedia, pk=pk, shop__in=shop_media.SHOP_LIBRARY)
    upload, error = _read_upload(request)
    if error:
        return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
    name, data = upload
    try:
        shop_media.replace(row, name, data, uploaded_by=request.user)
    except shop_media.MediaRejected as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_library(request.user))


@api_view(["POST"])
def reorder(request):
    if not _can_edit(request.user):
        return _forbidden()
    data = request.data if isinstance(request.data, dict) else {}
    shop = str(data.get("shop") or "").strip()
    if shop not in shop_media.SHOP_LIBRARY:
        return Response({"detail": "Choose Type 1, Type 2, Type 3 or the office."}, status=status.HTTP_400_BAD_REQUEST)
    ids = data.get("ids")
    if not isinstance(ids, list):
        return Response({"detail": "Send the files' ids as a list."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        shop_media.reorder(shop, ids)
    except shop_media.MediaRejected as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_library(request.user))


def _file_response(row: LeadAiShopMedia):
    if not row.file:
        return Response({"detail": "The file is not available."}, status=status.HTTP_404_NOT_FOUND)
    try:
        handle = row.file.open("rb")
    except OSError:
        return Response({"detail": "The file is not available."}, status=status.HTTP_404_NOT_FOUND)
    return FileResponse(handle, content_type=row.mime_type or "application/octet-stream", filename=row.file_name)


@api_view(["GET"])
def file(request, pk):
    return _file_response(get_object_or_404(LeadAiShopMedia, pk=pk, shop__in=shop_media.SHOP_LIBRARY))


# The studio and one-bedroom sets (batch 2e slice E): read only, every agent. ---------------------------------------


@api_view(["GET"])
def unit_library(request):
    return Response(unit_media.serialize_sets(request.user))


@api_view(["GET"])
def unit_file(request, pk):
    return _file_response(get_object_or_404(LeadAiShopMedia, pk=pk, unit_set__isnull=False))
