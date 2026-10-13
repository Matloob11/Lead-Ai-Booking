from apps.gateway.client import AlotsClient, AlotsError
c = AlotsClient()
pid = "1388181304374711"
for dest in ("+971500000000", "+447700900000"):
    try:
        c.send_text(pid, dest, "a")
        print(dest, "ok")
    except AlotsError as exc:
        print(dest, getattr(exc, "status_code", None), str(exc)[:120])
