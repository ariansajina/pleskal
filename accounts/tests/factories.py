import factory
from django.contrib.auth import get_user_model

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory[User]):
    class Meta:
        model = User
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda obj: f"{obj.username}@example.com")

    @factory.post_generation
    def password(
        self: User, create: bool, extracted: str | None, **kwargs: object
    ) -> None:
        password = extracted or "testpass123"
        self.set_password(password)
        if create:
            self.save(update_fields=["password"])
