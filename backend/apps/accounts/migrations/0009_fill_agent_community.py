from django.db import migrations

# From AGENTS DETAILS.pdf. Matched on the first word of display_name so
# "Ruqia Faisal" still maps when the PDF only says Ruqia. Alternate spellings
# (Harm/Haram, Shareen/Sheran, Tehreem/Tahreem) are the live Bitrix names.
# Only fills an empty community — an admin edit afterwards is left alone.
ROSTER = {
    "aila": "Villa Nova",
    "areeba": "Arabian Ranchers 3",
    "asma": "International city",
    "eman": "Arabian Ranchers 3",
    "esha": "Damac Hills 2",
    "fakhra": "Damac Lagoon",
    "farhat": "International city",
    "fozia": "International city",
    "haram": "Damac Lagoon, Malta, Santorini",
    "harm": "Damac Lagoon, Malta, Santorini",
    "irum": "The valley",
    "javeria": "Mudon Al Ranim",
    "khazeema": "Arabian Ranchers 3",
    "mehnaz": "Damac Hills 2",
    "minahil": "International city",
    "momina": "The valley",
    "nabiha": "Villa Nova",
    "nimra": "Damac Hills 2",
    "ruqia": "Mudon Al Ranim",
    "sapna": "Damac Lagoon, Nice",
    "shareen": "International city",
    "sheran": "International city",
    "tahreem": "Damac Hills 2",
    "tehreem": "Damac Hills 2",
    "uzma": "Damac Lagoon, Costa Brava, Portfino",
    "warda": "Damac Hills 2",
}


def _first_token(name):
    return (name or "").strip().split()[0].casefold() if name else ""


def fill_communities(apps, schema_editor):
    Agent = apps.get_model("accounts", "Agent")
    for agent in Agent.objects.all():
        if (agent.community or "").strip():
            continue
        community = ROSTER.get(_first_token(agent.display_name))
        if not community:
            continue
        agent.community = community
        agent.save(update_fields=["community"])


def noop_reverse(apps, schema_editor):
    # Do not blank communities on reverse — they may have been edited since.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_agent_community"),
    ]

    operations = [
        migrations.RunPython(fill_communities, noop_reverse),
    ]
