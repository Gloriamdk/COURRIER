import sqlite3
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from courrier.models import User

BACKUP_DB = "backups/db_before_outgoing_numbering_20260914_120224.sqlite3"

conn = sqlite3.connect(BACKUP_DB)
conn.row_factory = sqlite3.Row

cursor = conn.cursor()

cursor.execute("""
    SELECT
        id,
        password,
        last_login,
        is_superuser,
        username,
        first_name,
        last_name,
        email,
        is_staff,
        is_active,
        date_joined,
        role,
        service_direction
    FROM courrier_user
    ORDER BY id
""")

users = cursor.fetchall()

print(f"\nUtilisateurs trouvés dans le backup : {len(users)}\n")

restored = 0
skipped = 0

for row in users:

    username = row["username"]

    if User.objects.filter(username=username).exists():
        print(f"[EXISTE] {username}")
        skipped += 1
        continue

    user = User(
        id=row["id"],
        username=username,
        password=row["password"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        email=row["email"],
        is_superuser=bool(row["is_superuser"]),
        is_staff=bool(row["is_staff"]),
        is_active=bool(row["is_active"]),
        role=row["role"],
        service_direction=row["service_direction"],
    )

    if row["last_login"]:
        user.last_login = row["last_login"]

    if row["date_joined"]:
        user.date_joined = row["date_joined"]

    user.save(force_insert=True)

    print(f"[RESTAURE] {username}")
    restored += 1

conn.close()

print("\n==============================")
print(f"Restaurés : {restored}")
print(f"Déjà présents : {skipped}")
print("==============================")
print(f"Total actuel : {User.objects.count()}")




