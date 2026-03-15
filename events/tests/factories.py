import factory
from django.utils import timezone

from accounts.tests.factories import UserFactory

from ..models import Event, EventCategory, EventStatus


class EventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Event
        skip_postgeneration_save = True

    title = factory.Sequence(lambda n: f"Dance Event {n}")
    description = "A great dance event."
    start_datetime = factory.LazyFunction(
        lambda: timezone.now() + timezone.timedelta(days=7)
    )
    venue_name = "Dance Hall"
    category = EventCategory.SOCIAL
    status = EventStatus.PENDING
    submitted_by = factory.SubFactory(UserFactory)
