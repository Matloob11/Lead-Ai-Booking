"""Submit the International City shops templates to the sending numbers' WABAs (board T61).

    python manage.py submit_shops_templates --dry-run      what would be submitted, nothing sent
    python manage.py submit_shops_templates                 submit what is missing
    python manage.py submit_shops_templates --numbers 971581058719,971581058725

- intl_city_shops_followup (Template B, MARKETING, en): the one the automatic follow-ups send
  (followups.py); quick replies [Yes, book a viewing] [Not now].
- intl_city_shops_reconnect (Template A, MARKETING, en, VIDEO header): for Matloob to pick in the
  CRM popup; quick replies [Yes, show me shops] [Not now] [Stop messages]. Its header is reviewed
  against the Type 1 video of the Lead AI media library, uploaded once through the gateway's own
  template-sample route (the Template Center's "gateway" route: one handle serves every WABA).

The texts and the composer's fields are shop_templates.py's, with the rents of the shops facts as
they are now. Each template goes to each WABA of the numbers (default: the eight sending numbers,
board D4) that does not have it yet in ANY status or language, through apps.catalog's own create
(the Template Center's code, never a Meta call of its own). An existing template, or one hidden in
the panel, is never touched. Prints what it did per WABA.
"""

from __future__ import annotations

import re

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import WabaNumber, WaTemplate, WaTemplateHide
from apps.leadai import shop_templates
from apps.leadai.models import LeadAiSettings, LeadAiShopMedia

# The eight sending numbers (board D4): Coastline Properties / Blue Brick.
SENDING_NUMBERS = (
    "971581058719",
    "971581058720",
    "971581058721",
    "971581058722",
    "971581058723",
    "971581058724",
    "971581058725",
    "971581058726",
)
VIDEO_MIME = "video/mp4"


def digits(raw) -> str:
    return "".join(ch for ch in str(raw or "") if ch.isdigit())


def parse_numbers(raw: str) -> list[str]:
    """The numbers asked for (digits, country code first, a + allowed); CommandError for anything else."""
    if not str(raw or "").strip():
        return list(SENDING_NUMBERS)
    out = []
    for part in str(raw).split(","):
        text = part.strip()
        if not text:
            continue
        number = digits(text)
        if not re.fullmatch(r"\+?\d[\d ]*", text) or not 8 <= len(number) <= 15:
            raise CommandError(f"Not a phone number: '{text[:30]}'. Give digits with the country code, separated by commas.")
        if number not in out:
            out.append(number)
    if not out:
        raise CommandError("Give at least one number.")
    return out


def wabas_for(numbers: list[str]) -> tuple[dict, list[str]]:
    """({waba id: [phones]}, the lines for numbers that cannot be used)."""
    by_digits = {}
    for row in WabaNumber.objects.all().order_by("pk"):
        by_digits.setdefault(digits(row.phone_number), row)
    targets: dict[str, list[str]] = {}
    problems = []
    for number in numbers:
        row = by_digits.get(number)
        if row is None:
            problems.append(f"+{number}: no such number here, left out")
        elif not row.is_active:
            problems.append(f"+{number}: the number is not active, left out")
        elif not (row.waba_business_id or "").strip():
            problems.append(f"+{number}: the number has no WhatsApp Business account id, left out")
        else:
            phones = targets.setdefault(row.waba_business_id.strip(), [])
            if number not in phones:
                phones.append(number)
    return targets, problems


def existing(waba: str, name: str) -> str:
    """'' when the WABA has no such template in any status or language (nor hides one), else what it has."""
    rows = list(WaTemplate.objects.filter(waba_business_id=waba, name=name).values_list("status", "language"))
    if rows:
        return ", ".join(f"{status} ({language})" for status, language in rows)
    if WaTemplateHide.objects.filter(waba_business_id=waba, name=name).exists():
        return "hidden in the panel"
    return ""


def type_1_video() -> LeadAiShopMedia | None:
    return LeadAiShopMedia.objects.filter(shop=LeadAiShopMedia.Shop.TYPE_1, kind=LeadAiShopMedia.Kind.VIDEO).order_by("order", "pk").first()


def header_handle(video: LeadAiShopMedia) -> str:
    """The sample handle of the Type 1 video, minted through the gateway's template-sample route
    (AlotsClient.upload_sample, the Template Center's "gateway" route). Raises AlotsError or ValueError."""
    from apps.catalog.views import HEADER_SAMPLE_LIMITS, _sample_matches
    from apps.gateway.client import AlotsClient

    with video.file.open("rb") as handle:
        data = handle.read(HEADER_SAMPLE_LIMITS["VIDEO"] + 1)
    if not data or len(data) > HEADER_SAMPLE_LIMITS["VIDEO"] or not _sample_matches(data[:16], "VIDEO"):
        raise ValueError(f"{video.file_name} is not an MP4 of at most 16 MB")
    return AlotsClient().upload_sample(data, video.file_name, VIDEO_MIME)


class Command(BaseCommand):
    help = (
        f"Submit {shop_templates.FOLLOWUP_NAME} and {shop_templates.RECONNECT_NAME} to the sending numbers' WABAs "
        "that do not have them yet (any status)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Say what would be submitted; submit and upload nothing.")
        parser.add_argument(
            "--numbers", default="", metavar="9715...,...", help="Comma-separated numbers; default: the eight sending numbers."
        )

    def handle(self, *args, **options):
        from apps.catalog.views import _parse_template_form, _submit_template_to_waba

        dry = bool(options.get("dry_run"))
        numbers = parse_numbers(options.get("numbers") or "")
        targets, problems = wabas_for(numbers)
        for line in problems:
            self.stdout.write(self.style.WARNING(line))
        if not targets:
            raise CommandError("None of the numbers can take a template.")
        facts = LeadAiSettings.load().shops_facts
        self.stdout.write(f"{shop_templates.FOLLOWUP_NAME}: {shop_templates.followup_body(facts)}")
        self.stdout.write(f"  buttons: {' | '.join(shop_templates.FOLLOWUP_BUTTONS)}")
        self.stdout.write(f"{shop_templates.RECONNECT_NAME}: [video] {shop_templates.reconnect_body(facts)}")
        self.stdout.write(f"  buttons: {' | '.join(shop_templates.RECONNECT_BUTTONS)}")

        plan = {waba: {name: existing(waba, name) for name in shop_templates.NAMES} for waba in targets}
        needs_video = any(not have[shop_templates.RECONNECT_NAME] for have in plan.values())
        video = type_1_video() if needs_video else None
        handle, video_problem = "", ""
        if needs_video and video is None:
            video_problem = "the media library has no Type 1 video (Lead AI > Shop media), so it is not submitted"
        elif needs_video and dry:
            self.stdout.write(f"header sample: {video.file_name} ({video.size_bytes / (1024 * 1024):.1f} MB), uploaded on a real run")
        elif needs_video:
            from apps.gateway.client import AlotsError

            try:
                handle = header_handle(video)
                self.stdout.write(f"header sample: {video.file_name} uploaded through the gateway")
            except (AlotsError, OSError, ValueError) as exc:
                video_problem = f"the header sample did not upload ({str(exc)[:200]}), so it is not submitted"

        forms = {shop_templates.FOLLOWUP_NAME: shop_templates.followup_form(facts)}
        if handle:
            forms[shop_templates.RECONNECT_NAME] = shop_templates.reconnect_form(facts, handle)
        parsed = {}
        for name, form in forms.items():
            result, error = _parse_template_form(form)
            if error:
                raise CommandError(f"{name}: {error}")
            parsed[name] = result

        submitted = skipped = failed = 0
        for waba, phones in sorted(targets.items()):
            self.stdout.write(f"WABA {waba} ({', '.join('+' + phone for phone in phones)})")
            for name in shop_templates.NAMES:
                have = plan[waba][name]
                if have:
                    skipped += 1
                    self.stdout.write(f"  {name}: already {have}, left alone")
                elif name == shop_templates.RECONNECT_NAME and video_problem:
                    failed += 1
                    self.stdout.write(self.style.ERROR(f"  {name}: {video_problem}"))
                elif dry:
                    submitted += 1
                    self.stdout.write(f"  {name}: would be submitted")
                else:
                    template, error, was_skipped = _submit_template_to_waba(waba, parsed[name])
                    if error:
                        failed += 1
                        self.stdout.write(self.style.ERROR(f"  {name}: FAILED {error}"))
                    elif was_skipped:
                        skipped += 1
                        self.stdout.write(f"  {name}: Meta has it already ({getattr(template, 'status', '')}), left alone")
                    else:
                        submitted += 1
                        self.stdout.write(self.style.SUCCESS(f"  {name}: submitted, {template.status} at Meta"))
        verb = "would submit" if dry else "submitted"
        self.stdout.write(f"{verb}={submitted} skipped={skipped} failed={failed}")
        if not dry and submitted:
            self.stdout.write(
                "Meta must APPROVE them before use. Until Template B is approved on a number, its chats' automatic "
                "follow-ups wait (the Lead AI screen says so on each chat)."
            )
