"""Load the build pack's shop media folders into the Lead AI media library (board T30).

    python manage.py leadai_media_import /app/media/leadai_import            add them
    python manage.py leadai_media_import /app/media/leadai_import --dry-run  check and report only

Each folder under the directory is one shop: "Type 1 400 550sqft", the typo
"Tpye 2 700 800 sqft", "type-3" and "office" are recognised (anything else is
skipped with a line). Its files go in by name, the order they are sent in: an
MP4 (H.264) of at most 16 MB, JPEG or PNG photos of at most 5 MB, checked by
their bytes. A type takes one video and six photos, the office one photo; what
does not fit is reported, never silently dropped. A file that is in the
library already is left alone, so running it twice adds nothing twice.

On the live server it runs through `ops/wa.sh leadai-media-import DIR [--dry-run]`,
which takes a directory under /app/media/leadai_import only.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.leadai import shop_media


class Command(BaseCommand):
    help = "Import the shops media folders (Type 1/2/3, office) into the Lead AI media library."

    def add_arguments(self, parser):
        parser.add_argument("directory", help="The folder holding one folder per shop type.")
        parser.add_argument("--dry-run", action="store_true", help="Check and report, store nothing.")

    def handle(self, *args, directory, dry_run, **options):
        try:
            lines = shop_media.import_directory(directory, dry_run=dry_run)
        except shop_media.MediaRejected as exc:
            raise CommandError(str(exc)) from None
        for line in lines:
            self.stdout.write(line)
        added = sum(1 for line in lines if line.startswith(("added", "would add")))
        refused = sum(1 for line in lines if line.startswith(("refused", "left out")))
        verb = "would add" if dry_run else "added"
        self.stdout.write(f"{verb} {added} file(s); {refused} refused or left out; nothing stored" if dry_run else f"{verb} {added} file(s); {refused} refused or left out")
