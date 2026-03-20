"""
Encrypt the email field at rest.

Strategy:
1. Add email_hash (HMAC blind index, nullable) and email_enc (BinaryField,
   nullable) columns.
2. RunPython: encrypt every existing email into email_enc and compute
   email_hash.
3. SeparateDatabaseAndState: drop the old plaintext `email` column and add
   the unique constraint to email_hash, while updating Django's migration
   state so it agrees with the final model layout.

NOTE: EMAIL_ENCRYPTION_KEY and EMAIL_BLIND_INDEX_PEPPER must be set in the
environment before running this migration.
"""

import accounts.models
from django.db import migrations, models


def forward_encrypt(apps, schema_editor):
    """Encrypt existing plaintext emails into the new encrypted column."""
    from accounts.crypto import encrypt_email, hash_email

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, email FROM accounts_user"
            " WHERE email IS NOT NULL AND email != ''"
        )
        rows = cursor.fetchall()

    with schema_editor.connection.cursor() as cursor:
        for user_id, email in rows:
            encrypted = encrypt_email(email)
            h = hash_email(email)
            cursor.execute(
                "UPDATE accounts_user"
                " SET email_encrypted = %s, email_hash = %s"
                " WHERE id = %s",
                [encrypted, h, str(user_id)],
            )


def backward_decrypt(apps, schema_editor):
    """Decrypt emails from the encrypted column back to plaintext."""
    from accounts.crypto import decrypt_email

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, email_encrypted FROM accounts_user"
            " WHERE email_encrypted IS NOT NULL"
        )
        rows = cursor.fetchall()

    with schema_editor.connection.cursor() as cursor:
        for user_id, encrypted in rows:
            if encrypted:
                email = decrypt_email(bytes(encrypted))
                cursor.execute(
                    "UPDATE accounts_user SET email = %s WHERE id = %s",
                    [email, str(user_id)],
                )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_remove_user_is_approved_remove_user_is_moderator"),
    ]

    operations = [
        # Step 1: Add email_hash column (nullable, no unique constraint yet)
        migrations.AddField(
            model_name="user",
            name="email_hash",
            field=models.CharField(max_length=64, null=True, blank=True),
        ),
        # Step 2: Add encrypted email column under a temporary field name
        # (db_column='email_encrypted' is the permanent DB column name)
        migrations.AddField(
            model_name="user",
            name="email_enc",
            field=models.BinaryField(
                db_column="email_encrypted", null=True, blank=True, editable=True
            ),
        ),
        # Step 3: Fill in encrypted data before the plaintext column is dropped
        migrations.RunPython(forward_encrypt, backward_decrypt),
        # Step 4: Drop the old plaintext column and fix up the migration state
        # so Django agrees with the actual DB / model layout.
        migrations.SeparateDatabaseAndState(
            database_operations=[
                # Remove the old plaintext email column (drops UNIQUE too)
                migrations.RemoveField(model_name="user", name="email"),
                # Add unique constraint to email_hash
                migrations.AlterField(
                    model_name="user",
                    name="email_hash",
                    field=models.CharField(
                        max_length=64, unique=True, null=True, blank=True
                    ),
                ),
            ],
            state_operations=[
                # Remove the old email field from Django's state
                migrations.RemoveField(model_name="user", name="email"),
                # Rename the temp field to 'email' in state only
                # (the DB column is already named email_encrypted via db_column)
                migrations.RenameField(
                    model_name="user",
                    old_name="email_enc",
                    new_name="email",
                ),
                # Update the field type in state to match the model
                migrations.AlterField(
                    model_name="user",
                    name="email",
                    field=accounts.models.EncryptedEmailField(
                        db_column="email_encrypted"
                    ),
                ),
                # Mark email_hash as unique in state
                migrations.AlterField(
                    model_name="user",
                    name="email_hash",
                    field=models.CharField(
                        max_length=64, unique=True, null=True, blank=True
                    ),
                ),
            ],
        ),
    ]
