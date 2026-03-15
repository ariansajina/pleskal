"""Management command to import events scraped from dansehallerne.dk."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import Event, EventCategory, EventStatus


def make_aware_cph(naive_dt):
    """Convert a naive Copenhagen local datetime to UTC-aware."""
    import zoneinfo

    cph = zoneinfo.ZoneInfo("Europe/Copenhagen")
    return timezone.make_aware(naive_dt, cph)


# All events scraped from https://dansehallerne.dk/en/public-program/
# Each entry is a dict matching Event model fields.
EVENTS = [
    # ── IPAF 2026 ──────────────────────────────────────────────────────────
    {
        "title": "IPAF Festival Opening",
        "description": (
            "The festival directors invite you to celebrate the opening of IPAF 2026. "
            "The event features bubbles, speeches, and a spoken word performance by Rei Mansa, "
            "who focuses on themes of gender expression and sexuality with commentary on capitalism "
            "and societal norms.\n\n"
            "Part of IPAF 2026 (International Performance Art Festival) co-produced by Warehouse9 "
            "and Dansehallerne."
        ),
        "start_datetime": "2026-03-19 17:00",
        "end_datetime": "2026-03-19 18:00",
        "venue_name": "Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": True,
        "price_note": "Free admission",
        "source_url": "https://dansehallerne.dk/en/public-program/ipaf-performance/22294/",
    },
    {
        "title": "Charlie Laban Trier – Surfacing HypoKrisia",
        "description": (
            "A performative exploration featuring a series of performative efforts and spells "
            "centred on a mythological figure called HypoKrisia. The work investigates resilience "
            "through the guidance of a speculative, trans-mythic figure. The performer engages in "
            "a dance-duet that may result in a momentary possession, employing yells turned into "
            "songs, text-sampling, and sculptural movement.\n\n"
            "**Content notices:** Close proximity to performer possible. Loud music and extensive "
            "smoke effects. English language performance.\n\n"
            "Part of IPAF 2026."
        ),
        "start_datetime": "2026-03-19 18:00",
        "end_datetime": "2026-03-19 19:00",
        "venue_name": "Studio 4, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Pay what you can (sliding scale)",
        "source_url": "https://dansehallerne.dk/en/public-program/ipaf-performance/22238/",
    },
    {
        "title": "Eve Stainton – The Joystick and The Reins",
        "description": (
            "A choreographic solo performance exploring themes of power, threat, and marginalisation "
            "within society. The work cycles through hyper-emotional states of intensity and examines "
            "how marginalised groups have been instrumentalised through oppression. It draws influences "
            "from historical reenactments, police imagery, and 1980s crime television, accompanied by "
            "Ennio Morricone's score from The Thing (1982). The performance may invite audience "
            "participation in simple tasks that can be declined.\n\n"
            "Part of IPAF 2026."
        ),
        "start_datetime": "2026-03-19 20:00",
        "end_datetime": "2026-03-19 21:00",
        "venue_name": "Hallen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Pay what you can (sliding scale)",
        "source_url": "https://dansehallerne.dk/en/public-program/ipaf-performance/21634/",
    },
    {
        "title": "Eve Stainton – The Joystick and The Reins (20 Mar)",
        "description": (
            "A choreographic solo performance exploring themes of power, threat, and marginalisation "
            "within society. The work cycles through hyper-emotional states of intensity and examines "
            "how marginalised groups have been instrumentalised through oppression.\n\n"
            "Part of IPAF 2026."
        ),
        "start_datetime": "2026-03-20 19:00",
        "end_datetime": "2026-03-20 20:00",
        "venue_name": "Hallen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Pay what you can (sliding scale)",
        "source_url": "https://dansehallerne.dk/en/public-program/ipaf-performance/21634/",
    },
    {
        "title": "Eve Stainton – The Joystick and The Reins (21 Mar)",
        "description": (
            "A choreographic solo performance exploring themes of power, threat, and marginalisation "
            "within society. The work cycles through hyper-emotional states of intensity and examines "
            "how marginalised groups have been instrumentalised through oppression.\n\n"
            "Part of IPAF 2026."
        ),
        "start_datetime": "2026-03-21 19:00",
        "end_datetime": "2026-03-21 20:00",
        "venue_name": "Hallen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Pay what you can (sliding scale)",
        "source_url": "https://dansehallerne.dk/en/public-program/ipaf-performance/21634/",
    },
    {
        "title": "Alex Franz Zehetbauer – Bonappétitsixsixsix",
        "description": (
            "Performance artist and singer-songwriter Alex Franz Zehetbauer adopts the jester's "
            "skin – a figure with the ancient privilege to say and do anything without punishment. "
            "The work transforms his body into a leaking instrument for his heartfelt songs, "
            "accompanied by hydrophones and a lyre, blending performance, music, and choreography.\n\n"
            "Part of IPAF 2026."
        ),
        "start_datetime": "2026-03-20 17:00",
        "end_datetime": "2026-03-20 18:00",
        "venue_name": "Loftet, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Pay what you can (sliding scale)",
        "source_url": "https://dansehallerne.dk/en/public-program/ipaf-performance/22260/",
    },
    {
        "title": "Alex Franz Zehetbauer – Bonappétitsixsixsix (21 Mar)",
        "description": (
            "Performance artist and singer-songwriter Alex Franz Zehetbauer adopts the jester's "
            "skin – a figure with the ancient privilege to say and do anything without punishment. "
            "The work transforms his body into a leaking instrument for his heartfelt songs, "
            "accompanied by hydrophones and a lyre, blending performance, music, and choreography.\n\n"
            "Part of IPAF 2026."
        ),
        "start_datetime": "2026-03-21 15:30",
        "end_datetime": "2026-03-21 16:30",
        "venue_name": "Loftet, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Pay what you can (sliding scale)",
        "source_url": "https://dansehallerne.dk/en/public-program/ipaf-performance/22260/",
    },
    {
        "title": "Lucy McCormick – Lucy & Friends",
        "description": (
            "A queer cabaret spectacular combining pole dancing, cat impersonation, clairvoyance, "
            "and social policy commentary. The show explores community and connection through "
            "theatrical manipulation, vulnerability, and irreverence.\n\n"
            "**Content warnings:** Haze, strobe lighting, loud noise, strong language, sexual "
            "content, and nudity. No filming or photography permitted. Age restriction: 18+\n\n"
            "Part of IPAF 2026."
        ),
        "start_datetime": "2026-03-20 21:00",
        "end_datetime": "2026-03-20 22:00",
        "venue_name": "Blackboxen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Pay what you can (sliding scale)",
        "source_url": "https://dansehallerne.dk/en/public-program/ipaf-performance/22204/",
    },
    {
        "title": "Lucy McCormick – Lucy & Friends (21 Mar)",
        "description": (
            "A queer cabaret spectacular combining pole dancing, cat impersonation, clairvoyance, "
            "and social policy commentary. The show explores community and connection through "
            "theatrical manipulation, vulnerability, and irreverence.\n\n"
            "**Content warnings:** Haze, strobe lighting, loud noise, strong language, sexual "
            "content, and nudity. No filming or photography permitted. Age restriction: 18+\n\n"
            "Part of IPAF 2026."
        ),
        "start_datetime": "2026-03-21 21:00",
        "end_datetime": "2026-03-21 22:00",
        "venue_name": "Blackboxen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Pay what you can (sliding scale)",
        "source_url": "https://dansehallerne.dk/en/public-program/ipaf-performance/22204/",
    },
    {
        "title": "Hazem Header – MANEATER",
        "description": (
            "A solo contemporary dance performance exploring Egypt's complex relationship with its "
            "rulers and people. The work combines Egyptian folk dance with evocative traditional "
            "songs and political speeches, examining themes of patriotism, disillusionment, hope, "
            "and oppression through intricate physicality.\n\n"
            "Part of IPAF 2026."
        ),
        "start_datetime": "2026-03-21 17:00",
        "end_datetime": "2026-03-21 18:05",
        "venue_name": "Studio 4, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Pay what you can (sliding scale)",
        "source_url": "https://dansehallerne.dk/en/public-program/ipaf-performance/22273/",
    },
    {
        "title": "Hazem Header – MANEATER (22 Mar)",
        "description": (
            "A solo contemporary dance performance exploring Egypt's complex relationship with its "
            "rulers and people. The work combines Egyptian folk dance with evocative traditional "
            "songs and political speeches, examining themes of patriotism, disillusionment, hope, "
            "and oppression through intricate physicality.\n\n"
            "Part of IPAF 2026."
        ),
        "start_datetime": "2026-03-22 17:00",
        "end_datetime": "2026-03-22 18:05",
        "venue_name": "Studio 4, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Pay what you can (sliding scale)",
        "source_url": "https://dansehallerne.dk/en/public-program/ipaf-performance/22273/",
    },
    {
        "title": "Artist Talk: Queer Art in Egypt",
        "description": (
            "Following the MANEATER performance, audiences are invited to discuss queer artistic "
            "expression in Egypt with two speakers: Hazem Header (Egyptian choreographer and dancer, "
            "founder of Cairo's first international site-specific performance festival) and Niels "
            "Bjørn (podcaster and urbanist documenting LGBT+ experiences in Egypt).\n\n"
            "The artist talk follows immediately after MANEATER. Free admission."
        ),
        "start_datetime": "2026-03-22 18:00",
        "end_datetime": "2026-03-22 19:00",
        "venue_name": "Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.OTHER,
        "is_free": True,
        "price_note": "Free admission",
        "source_url": "https://dansehallerne.dk/en/public-program/ipaf-performance/23136/",
    },
    # ── Spring Performances ────────────────────────────────────────────────
    {
        "title": "Marie Topp / Visible Effects – The Labyrinth",
        "description": (
            "A choreographic work exploring the acceleration and passage of time through personal "
            "experiences of birth and death. The performance features three characters embodying "
            "different emotional states, moving through a blurred, yet alluring landscape of light "
            "with an immersive soundscape.\n\n"
            "Described as \"a masterpiece that grips the audience\" (Statens Kunstfonds "
            "Legatudvalget for Scenekunst 2024)."
        ),
        "start_datetime": "2026-03-27 20:00",
        "end_datetime": "2026-03-27 21:00",
        "venue_name": "Blackboxen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/21474/",
    },
    {
        "title": "Marie Topp / Visible Effects – The Labyrinth (28 Mar)",
        "description": (
            "A choreographic work exploring the acceleration and passage of time through personal "
            "experiences of birth and death. The performance features three characters embodying "
            "different emotional states, moving through a blurred, yet alluring landscape of light "
            "with an immersive soundscape."
        ),
        "start_datetime": "2026-03-28 17:00",
        "end_datetime": "2026-03-28 18:00",
        "venue_name": "Blackboxen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/21474/",
    },
    {
        "title": "Andrea Zavala Folache & Adriano Wilfert Jensen – Domestic Anarchism: Bailes",
        "description": (
            "A performance exploring transmitting dances from body to body across context, combining "
            "wrestling, telekinesis, stand-up comedy, and improvisation. Materials emerged through "
            "intimate collaborations addressing family-related issues. Part of the long-term research "
            "project *Domestic Anarchism*."
        ),
        "start_datetime": "2026-04-14 20:00",
        "end_datetime": "2026-04-14 21:00",
        "venue_name": "Hallen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/21342/",
    },
    {
        "title": "Andrea Zavala Folache & Adriano Wilfert Jensen – Domestic Anarchism: Bailes (16 Apr)",
        "description": (
            "A performance exploring transmitting dances from body to body across context, combining "
            "wrestling, telekinesis, stand-up comedy, and improvisation. Part of the long-term "
            "research project *Domestic Anarchism*."
        ),
        "start_datetime": "2026-04-16 20:00",
        "end_datetime": "2026-04-16 21:00",
        "venue_name": "Hallen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/21342/",
    },
    {
        "title": "Andrea Zavala Folache & Adriano Wilfert Jensen – Domestic Anarchism: Bailes (17 Apr)",
        "description": (
            "A performance exploring transmitting dances from body to body across context, combining "
            "wrestling, telekinesis, stand-up comedy, and improvisation. Part of the long-term "
            "research project *Domestic Anarchism*."
        ),
        "start_datetime": "2026-04-17 20:00",
        "end_datetime": "2026-04-17 21:00",
        "venue_name": "Hallen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/21342/",
    },
    {
        "title": "Andrea Zavala Folache & Adriano Wilfert Jensen – Domestic Anarchism: Bailes (18 Apr)",
        "description": (
            "A performance exploring transmitting dances from body to body across context, combining "
            "wrestling, telekinesis, stand-up comedy, and improvisation. Part of the long-term "
            "research project *Domestic Anarchism*."
        ),
        "start_datetime": "2026-04-18 17:00",
        "end_datetime": "2026-04-18 18:00",
        "venue_name": "Hallen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/21342/",
    },
    {
        "title": "Simone Wierød & Carl Emil Carlsen – Dualities",
        "description": (
            "A technologically innovative dance performance where choreography meets 3D video "
            "projections, exploring the relationship between our real selves and our digital "
            "identities. The production investigates identity, self-image, and mirrored realities "
            "in both online and offline contexts through hypnotic reflections and optical illusions."
        ),
        "start_datetime": "2026-04-21 20:00",
        "end_datetime": "2026-04-21 21:00",
        "venue_name": "Blackboxen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/21751/",
    },
    {
        "title": "Simone Wierød & Carl Emil Carlsen – Dualities (23 Apr)",
        "description": (
            "A technologically innovative dance performance where choreography meets 3D video "
            "projections, exploring the relationship between our real selves and our digital "
            "identities through hypnotic reflections and optical illusions."
        ),
        "start_datetime": "2026-04-23 20:00",
        "end_datetime": "2026-04-23 21:00",
        "venue_name": "Blackboxen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/21751/",
    },
    {
        "title": "Simone Wierød & Carl Emil Carlsen – Dualities (24 Apr)",
        "description": (
            "A technologically innovative dance performance where choreography meets 3D video "
            "projections, exploring the relationship between our real selves and our digital "
            "identities through hypnotic reflections and optical illusions."
        ),
        "start_datetime": "2026-04-24 20:00",
        "end_datetime": "2026-04-24 21:00",
        "venue_name": "Blackboxen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/21751/",
    },
    {
        "title": "Simone Wierød & Carl Emil Carlsen – Dualities (25 Apr)",
        "description": (
            "A technologically innovative dance performance where choreography meets 3D video "
            "projections, exploring the relationship between our real selves and our digital "
            "identities through hypnotic reflections and optical illusions."
        ),
        "start_datetime": "2026-04-25 17:00",
        "end_datetime": "2026-04-25 18:00",
        "venue_name": "Blackboxen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/21751/",
    },
    {
        "title": "Institute of Interconnected Realities – TERRA UMBRAE",
        "description": (
            "A choreographic landscape featuring eight performers and one musician exploring the "
            "connection between body and landscape. The piece examines how landscapes we've bonded "
            "with live on in us as elastic impressions, drawing from four years of research in "
            "Danish landscapes. Shadows, echoes and living memories through dance, sound, and "
            "scenography."
        ),
        "start_datetime": "2026-05-06 20:00",
        "end_datetime": "2026-05-06 21:00",
        "venue_name": "Hallen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/21681/",
    },
    {
        "title": "Institute of Interconnected Realities – TERRA UMBRAE (8 May)",
        "description": (
            "A choreographic landscape featuring eight performers and one musician exploring the "
            "connection between body and landscape, drawing from four years of research in Danish "
            "landscapes."
        ),
        "start_datetime": "2026-05-08 20:00",
        "end_datetime": "2026-05-08 21:00",
        "venue_name": "Hallen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/21681/",
    },
    {
        "title": "Institute of Interconnected Realities – TERRA UMBRAE (9 May)",
        "description": (
            "A choreographic landscape featuring eight performers and one musician exploring the "
            "connection between body and landscape, drawing from four years of research in Danish "
            "landscapes."
        ),
        "start_datetime": "2026-05-09 17:00",
        "end_datetime": "2026-05-09 18:00",
        "venue_name": "Hallen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/21681/",
    },
    {
        "title": "Institute of Interconnected Realities – TERRA UMBRAE (10 May)",
        "description": (
            "A choreographic landscape featuring eight performers and one musician exploring the "
            "connection between body and landscape, drawing from four years of research in Danish "
            "landscapes."
        ),
        "start_datetime": "2026-05-10 17:00",
        "end_datetime": "2026-05-10 18:00",
        "venue_name": "Hallen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/21681/",
    },
    {
        "title": "AVIAJA Dance – WHITEOUT",
        "description": (
            "A thought-provoking dance performance exploring grief and loss through the metaphor of "
            "an Arctic whiteout. The work addresses the painful longing, unbearable thoughts, shame, "
            "and taboos surrounding suicide while celebrating life-affirming aspects of connection "
            "and community.\n\n"
            "Winner of Dance Performance of the Year at Årets Reumert Awards 2025."
        ),
        "start_datetime": "2026-05-28 18:00",
        "end_datetime": "2026-05-28 19:00",
        "venue_name": "Hallen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/22633/",
    },
    {
        "title": "AVIAJA Dance – WHITEOUT (29 May)",
        "description": (
            "A thought-provoking dance performance exploring grief and loss through the metaphor of "
            "an Arctic whiteout. Winner of Dance Performance of the Year at Årets Reumert Awards 2025."
        ),
        "start_datetime": "2026-05-29 20:00",
        "end_datetime": "2026-05-29 21:00",
        "venue_name": "Hallen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/22633/",
    },
    {
        "title": "AVIAJA Dance – WHITEOUT (30 May)",
        "description": (
            "A thought-provoking dance performance exploring grief and loss through the metaphor of "
            "an Arctic whiteout. Winner of Dance Performance of the Year at Årets Reumert Awards 2025."
        ),
        "start_datetime": "2026-05-30 16:00",
        "end_datetime": "2026-05-30 17:00",
        "venue_name": "Hallen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/22633/",
    },
    {
        "title": "AVIAJA Dance – WHITEOUT (31 May)",
        "description": (
            "A thought-provoking dance performance exploring grief and loss through the metaphor of "
            "an Arctic whiteout. Winner of Dance Performance of the Year at Årets Reumert Awards 2025."
        ),
        "start_datetime": "2026-05-31 15:00",
        "end_datetime": "2026-05-31 16:00",
        "venue_name": "Hallen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/22633/",
    },
    {
        "title": "Convoi Exceptionnel – Detached from Others",
        "description": (
            "A choreographic exploration of loneliness performed by dancer Kenzo Kusuda, accompanied "
            "by organ music composed by Lil Lacy. The work examines solitude's dual nature – both as "
            "introspective respite and involuntary isolation. Quadraphonic sound mixing with layered "
            "recordings creates an immersive and sensual soundscape."
        ),
        "start_datetime": "2026-05-28 20:00",
        "end_datetime": "2026-05-28 21:00",
        "venue_name": "Blackboxen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/22448/",
    },
    {
        "title": "Convoi Exceptionnel – Detached from Others (29 May)",
        "description": (
            "A choreographic exploration of loneliness by Kenzo Kusuda with organ music by Lil Lacy. "
            "Examines solitude's dual nature through quadraphonic soundscapes."
        ),
        "start_datetime": "2026-05-29 18:00",
        "end_datetime": "2026-05-29 19:00",
        "venue_name": "Blackboxen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/22448/",
    },
    {
        "title": "Convoi Exceptionnel – Detached from Others (30 May)",
        "description": (
            "A choreographic exploration of loneliness by Kenzo Kusuda with organ music by Lil Lacy. "
            "Examines solitude's dual nature through quadraphonic soundscapes."
        ),
        "start_datetime": "2026-05-30 18:00",
        "end_datetime": "2026-05-30 19:00",
        "venue_name": "Blackboxen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/22448/",
    },
    {
        "title": "Convoi Exceptionnel – Detached from Others (31 May)",
        "description": (
            "A choreographic exploration of loneliness by Kenzo Kusuda with organ music by Lil Lacy. "
            "Examines solitude's dual nature through quadraphonic soundscapes."
        ),
        "start_datetime": "2026-05-31 17:00",
        "end_datetime": "2026-05-31 18:00",
        "venue_name": "Blackboxen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/22448/",
    },
    {
        "title": "Spine Fiction – Amygdala",
        "description": (
            "A sensory dance performance for infants and toddlers (ages 3–24 months) exploring "
            "prenatal experience. The piece uses light, sound, and movement to create a sensory "
            "adventure where heartbeats become rhythms and breath becomes music – a glimpse of the "
            "time we all share before we were born."
        ),
        "start_datetime": "2026-06-13 11:00",
        "end_datetime": "2026-06-13 11:40",
        "venue_name": "Blackboxen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/21390/",
    },
    {
        "title": "Spine Fiction – Amygdala (15–20 Jun)",
        "description": (
            "A sensory dance performance for infants and toddlers (ages 3–24 months) exploring "
            "prenatal experience through light, sound, and movement. Daily performances 15–20 June "
            "at 09:30."
        ),
        "start_datetime": "2026-06-15 09:30",
        "end_datetime": "2026-06-15 10:10",
        "venue_name": "Blackboxen, Dansehallerne",
        "venue_address": "Franciska Clausens Plads 27, 1799 Copenhagen V",
        "category": EventCategory.PERFORMANCE,
        "is_free": False,
        "price_note": "Tickets available",
        "source_url": "https://dansehallerne.dk/en/public-program/performance/21390/",
    },
]


class Command(BaseCommand):
    help = "Import events scraped from dansehallerne.dk/en/public-program/"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be imported without saving to the database.",
        )

    def handle(self, *args, **options):
        import datetime

        dry_run = options["dry_run"]
        created = 0
        skipped = 0

        for data in EVENTS:
            source_url = data["source_url"]
            title = data["title"]

            # Skip duplicates by (title, source_url)
            if Event.objects.filter(title=title, source_url=source_url).exists():
                self.stdout.write(f"  SKIP  {title}")
                skipped += 1
                continue

            start_naive = datetime.datetime.strptime(data["start_datetime"], "%Y-%m-%d %H:%M")
            end_naive = (
                datetime.datetime.strptime(data["end_datetime"], "%Y-%m-%d %H:%M")
                if data.get("end_datetime")
                else None
            )

            start_dt = make_aware_cph(start_naive)
            end_dt = make_aware_cph(end_naive) if end_naive else None

            if dry_run:
                self.stdout.write(f"  DRY   {title}  ({start_dt})")
                created += 1
                continue

            event = Event(
                title=title,
                description=data.get("description", ""),
                start_datetime=start_dt,
                end_datetime=end_dt,
                venue_name=data["venue_name"],
                venue_address=data.get("venue_address", ""),
                category=data["category"],
                is_free=data.get("is_free", False),
                price_note=data.get("price_note", ""),
                source_url=source_url,
                external_source="dansehallerne",
                submitted_by=None,
                status=EventStatus.APPROVED,
            )
            # Skip clean() date-in-future validation for imported past/future events
            event.save()
            self.stdout.write(self.style.SUCCESS(f"  CREATED  {title}"))
            created += 1

        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry run: {created} would be created, {skipped} skipped."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Done: {created} created, {skipped} skipped."))
