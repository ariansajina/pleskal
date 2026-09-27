from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from events.models import Event


def _delete_image_if_unreferenced(storage, name: str) -> None:
    # Don't delete the file if another event still references the same path
    if Event.objects.filter(image=name).exists():
        return
    storage.delete(name)


@receiver(post_delete, sender=Event)
def delete_event_image_on_delete(sender, instance, **kwargs):
    if not (instance.image and instance.image.name):
        return
    _delete_image_if_unreferenced(instance.image.storage, instance.image.name)


@receiver(pre_save, sender=Event)
def remember_previous_image(sender, instance, update_fields=None, **kwargs):
    """Record the stored image path so post_save can tell if it was replaced."""
    instance._previous_image_name = ""
    if instance._state.adding or instance.pk is None:
        return
    if update_fields is not None and "image" not in update_fields:
        return
    instance._previous_image_name = (
        Event.objects.filter(pk=instance.pk).values_list("image", flat=True).first()
        or ""
    )


@receiver(post_save, sender=Event)
def delete_replaced_event_image(sender, instance, created, **kwargs):
    """Remove the old file when an event's image is replaced or cleared.

    Media is served from a public bucket, so an orphaned file would stay
    reachable at its old URL after the owner removed it from the event.
    """
    previous = getattr(instance, "_previous_image_name", "")
    current = instance.image.name if instance.image else ""
    if created or not previous or previous == current:
        return
    storage = instance.image.storage
    transaction.on_commit(lambda: _delete_image_if_unreferenced(storage, previous))
