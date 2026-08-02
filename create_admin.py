import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django.setup()

from separator.users.models import User

if not User.objects.filter(email="admin@example.com").exists():
    User.objects.create_superuser(email="admin@example.com", password="admin123456")
    print("SUPERUSER admin@example.com CREATED SUCCESSFULLY! Password: admin123456")
else:
    u = User.objects.get(email="admin@example.com")
    u.set_password("admin123456")
    u.save()
    print("SUPERUSER admin@example.com PASSWORD RESET SUCCESSFULLY to: admin123456")
