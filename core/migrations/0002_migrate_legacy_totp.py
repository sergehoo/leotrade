import base64

from django.db import migrations


def migrate_legacy_totp(apps, schema_editor):
    from allauth.mfa.utils import encrypt

    Authenticator = apps.get_model("mfa", "Authenticator")
    TOTPDevice = apps.get_model("otp_totp", "TOTPDevice")

    migrated_users = set(
        Authenticator.objects.filter(type="totp").values_list("user_id", flat=True)
    )
    devices = TOTPDevice.objects.filter(confirmed=True).order_by(
        "user_id",
        "-last_used_at",
        "-created_at",
        "-id",
    )

    for device in devices.iterator():
        if device.user_id in migrated_users:
            continue
        secret = base64.b32encode(bytes.fromhex(device.key)).decode("ascii")
        Authenticator.objects.create(
            user_id=device.user_id,
            type="totp",
            data={"secret": encrypt(secret)},
        )
        migrated_users.add(device.user_id)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("mfa", "0001_initial"),
        ("otp_totp", "0003_add_timestamps"),
    ]

    operations = [
        migrations.RunPython(migrate_legacy_totp, migrations.RunPython.noop),
    ]
