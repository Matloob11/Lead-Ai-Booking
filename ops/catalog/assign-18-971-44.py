"""One-off: these 18 agents each get one 44 and one 971. Nobody else keeps a number.

Removals deactivate NumberAssignment rows. WabaNumber rows are never deleted.
"""

from django.db import transaction

from apps.accounts.models import Agent
from apps.catalog.models import NumberAssignment, WabaNumber

# display_name -> (uk 44, uae 971)
KEEP = {
    "Aila Shehzadi": ("447366360875", "971555716422"),
    "Areeba": ("447414115945", "971555956439"),
    "Khazeema": ("447426912372", "971555497521"),
    "eman Fazal": ("447414121510", "971555306149"),
    "NABIHA": ("447360267436", "971559759052"),
    "SAPNA": ("447462178442", "971559632895"),
    "uzma jamshaid": ("447447179547", "971555832603"),
    "tehreem Ijaaz": ("447723321328", "971524473103"),
    "Mehreen": ("447447178015", "971557466914"),
    "mehnaz": ("447428322124", "971559481572"),
    "nimra akbar": ("447723461484", "971555689029"),
    "Esha Ghazi": ("447426758743", "971559668904"),
    "Warda Hassan": ("447360545726", "971555850765"),
    "Farhat Shahid": ("447723430080", "971559477395"),
    "shareen Shahid": ("447447184236", "971559430556"),
    "Asma Aslam": ("447447187245", "971524492026"),
    "minahil sanaullah": ("447401457395", "971524077268"),
    "Fozia razzaq": ("447455749638", "971555817694"),
}

# Numbers that change hands or were empty — set the holder's name.
RELABEL = {
    "447447179547": "uzma jamshaid",
    "447447184236": "shareen Shahid",
    "447447187245": "Asma Aslam",
    "447455749638": "Fozia razzaq",
    "971559759052": "NABIHA",
    "971559632895": "SAPNA",
    "971557466914": "Mehreen",
}


def _activate(number, agent, actor):
    rows = list(
        NumberAssignment.objects.filter(number=number, agent=agent).order_by("-is_active", "-id")
    )
    if rows:
        keep = rows[0]
        keep.role = NumberAssignment.Role.PRIMARY
        keep.is_active = True
        keep.created_by = actor
        keep.save(update_fields=["role", "is_active", "created_by"])
        NumberAssignment.objects.filter(number=number, agent=agent).exclude(pk=keep.pk).update(
            is_active=False
        )
        return "reuse"
    NumberAssignment.objects.create(
        number=number,
        agent=agent,
        role=NumberAssignment.Role.PRIMARY,
        is_active=True,
        created_by=actor,
    )
    return "create"


def main():
    actor = Agent.objects.filter(pk=3).first()
    wanted = {}
    for name, (uk, uae) in KEEP.items():
        agents = list(Agent.objects.filter(display_name=name, is_active=True))
        if len(agents) != 1:
            raise RuntimeError(f"agent {name!r} matched {len(agents)}")
        agent = agents[0]
        for phone in (uk, uae):
            number = WabaNumber.objects.filter(phone_number=phone, is_active=True).first()
            if not number:
                raise RuntimeError(f"missing active number {phone}")
            key = (number.id, agent.id)
            if key in wanted:
                raise RuntimeError(f"duplicate pair {phone} / {name}")
            wanted[key] = (number, agent, phone)

    phones = [phone for _, _, phone in wanted.values()]
    if len(set(phones)) != len(phones):
        raise RuntimeError("a number is assigned to two keepers")

    with transaction.atomic():
        drop_pks = [
            row.pk
            for row in NumberAssignment.objects.filter(is_active=True)
            if (row.number_id, row.agent_id) not in wanted
        ]
        dropped = NumberAssignment.objects.filter(pk__in=drop_pks).update(is_active=False) if drop_pks else 0
        actions = []
        for number, agent, phone in wanted.values():
            actions.append(f"{_activate(number, agent, actor)}\t{agent.display_name}\t{phone}")
            new_label = RELABEL.get(phone)
            if new_label is not None and number.label != new_label:
                number.label = new_label
                number.save(update_fields=["label"])

    leftover = NumberAssignment.objects.filter(is_active=True).exclude(
        number_id__in=[n.id for n, _, _ in wanted.values()],
        agent_id__in=[a.id for _, a, _ in wanted.values()],
    )
    # The exclude above is OR-ish in Django (AND of two __in). Check properly:
    leftover = [
        row
        for row in NumberAssignment.objects.filter(is_active=True).select_related("agent", "number")
        if (row.number_id, row.agent_id) not in wanted
    ]
    if leftover:
        raise RuntimeError(
            "leftover active assignments: "
            + ", ".join(f"{r.agent.display_name}:{r.number.phone_number}" for r in leftover)
        )

    print(f"deactivated={dropped} keepers={len(KEEP)} assignments={len(wanted)}", flush=True)
    for line in sorted(actions):
        print(line, flush=True)

    counts = {}
    for row in (
        NumberAssignment.objects.filter(is_active=True)
        .select_related("agent", "number")
        .order_by("agent__display_name", "number__phone_number")
    ):
        counts.setdefault(row.agent.display_name, []).append(row.number.phone_number)
        print(
            f"live\t{row.agent.display_name}\t{row.number.phone_number}",
            flush=True,
        )
    if set(counts) != set(KEEP):
        raise RuntimeError(f"live agents {sorted(counts)} != keepers")
    for name, phones in counts.items():
        uk = [p for p in phones if p.startswith("44")]
        uae = [p for p in phones if p.startswith("971")]
        if len(phones) != 2 or len(uk) != 1 or len(uae) != 1:
            raise RuntimeError(f"{name} ended with {phones}")


main()
