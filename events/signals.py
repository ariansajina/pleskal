from django.db.models.signals import post_delete
from django.dispatch import receiver

from events.models import Event


@receiver(post_delete, sender=Event)
def delete_event_image_on_delete(sender, instance, **kwargs):
    if not (instance.image and instance.image.name):
        return
    # Don't delete the file if another event still references the same path
    if Event.objects.filter(image=instance.image.name).exists():
        return
    instance.image.storage.delete(instance.image.name)
