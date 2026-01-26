import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nota_db.settings')
django.setup()

from django.contrib.auth import get_user_model

def create_or_reset_superuser():
    User = get_user_model()
    username = 'admin'
    password = 'password'
    email = 'admin@example.com'

    try:
        if not User.objects.filter(username=username).exists():
            print(f"Creating superuser '{username}'...")
            User.objects.create_superuser(username, email, password)
            print(f"Superuser '{username}' created successfully.")
        else:
            print(f"Superuser '{username}' already exists. Resetting password...")
            u = User.objects.get(username=username)
            u.set_password(password)
            u.save()
            print(f"Password for '{username}' has been reset to '{password}'.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    create_or_reset_superuser()
