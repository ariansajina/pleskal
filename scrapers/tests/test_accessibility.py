import pytest

from scrapers.accessibility import wheelchair_access_from_text


@pytest.mark.parametrize(
    "text",
    [
        "ISNÆTTER is accessible for wheelchair users and guests with reduced mobility.",
        "Forestillingen er tilgængelig for kørestolsbrugere",
        (
            "Warehouse9 has level free entrance to the space and a gender neutral "
            "accessible toilet that can be accessed via a certified stairlift."
        ),
        "Niveaufri adgang for kørestolsbrugere via hovedindgangen.",
        "Kørestolstoilet findes i Spor10s lokaler.",
        "The venue is step-free.\nNo stairs anywhere.",
    ],
)
def test_affirmed(text):
    assert wheelchair_access_from_text(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "The theatre is not wheelchair accessible.",
        "Bemærk at teatret ikke er kørestolsvenligt.",
        "Desværre er der ingen niveaufri adgang.",
        "Unfortunately there is no step-free access to the stage.",
        # A denial wins over an affirmation elsewhere in the text.
        "Accessible for wheelchair users. The gallery is not wheelchair accessible.",
    ],
)
def test_denied(text):
    assert wheelchair_access_from_text(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "",
        None,
        "Accessible for non-Danish speakers",
        "Vi beklager meget, at vi ikke kan tilbyde et handicaptoilet.",
        "There may be strobe lights and haze.",
    ],
)
def test_silent(text):
    assert wheelchair_access_from_text(text) is None


def test_denied_toilet_does_not_deny_the_entrance():
    text = "No accessible toilet, but the entrance is step-free."
    assert wheelchair_access_from_text(text) is True
