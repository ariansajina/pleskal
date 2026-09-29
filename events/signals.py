from functools import partial

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from events.models import Event, EventSeries

# Stored files per event. Thumbnails are content-addressed and shared between
# events with the same image, so every deletion checks for other references.
FILE_FIELDS = ("image", "thumbnail")


def _delete_file_if_unreferenced(field_name: str, storage, name: str) -> None:
    # Don't delete the file if another event still references the same path
    if Event.objects.filter(**{field_name: name}).exists():
        return
    storage.delete(name)


@receiver(post_delete, sender=Event)
def delete_event_image_on_delete(sender, instance, **kwargs):
    for field_name in FILE_FIELDS:
        file = getattr(instance, field_name)
        if not (file and file.name):
            continue
        _delete_file_if_unreferenced(field_name, file.storage, file.name)


@receiver(post_delete, sender=Event)
def delete_empty_series(sender, instance, **kwargs):
    """A recurring event's series goes with its last occurrence."""
    series_id = instance.series_id
    if series_id and not Event.objects.filter(series_id=series_id).exists():
        EventSeries.objects.filter(pk=series_id).delete()


@receiver(pre_save, sender=Event)
def remember_previous_files(sender, instance, update_fields=None, **kwargs):
    """Record the stored file paths so post_save can tell if they were replaced."""
    instance._previous_file_names = {}
    if instance._state.adding or instance.pk is None:
        return
    fields = [f for f in FILE_FIELDS if update_fields is None or f in update_fields]
    if not fields:
        return
    row = Event.objects.filter(pk=instance.pk).values(*fields).first() or {}
    instance._previous_file_names = {f: row.get(f) or "" for f in fields}


@receiver(post_save, sender=Event)
def delete_replaced_event_files(sender, instance, created, **kwargs):
    """Remove old files when an event's image (and so its thumbnail) is
    replaced or cleared.

    Media is served from a public bucket, so an orphaned file would stay
    reachable at its old URL after the owner removed it from the event.
    """
    if created:
        return
    for field_name, previous in getattr(instance, "_previous_file_names", {}).items():
        file = getattr(instance, field_name)
        current = file.name if file else ""
        if not previous or previous == current:
            continue
        transaction.on_commit(
            partial(_delete_file_if_unreferenced, field_name, file.storage, previous)
        )
