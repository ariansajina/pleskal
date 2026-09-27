from django.db.models.signals import post_delete
from django.dispatch import receiver

from events.models import Event


@receiver(post_delete, sender=Event)
def delete_event_image_on_delete(sender, instance, **kwargs):
    for field_name in ("image", "thumbnail"):
        file = getattr(instance, field_name)
        if not (file and file.name):
            continue
        # Don't delete the file if another event still references the same path
        if Event.objects.filter(**{field_name: file.name}).exists():
            continue
        file.storage.delete(file.name)
