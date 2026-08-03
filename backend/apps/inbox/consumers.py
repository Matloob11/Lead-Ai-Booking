from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .events import group_for_admins, group_for_agent, group_for_number


class InboxConsumer(AsyncJsonWebsocketConsumer):
    """Streams inbox activity for every number the connected agent can see."""

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return

        self.groups_joined = await self._number_groups(user)
        for group in self.groups_joined:
            await self.channel_layer.group_add(group, self.channel_name)

        await self.accept()
        await self.send_json({"event": "ready", "data": {"numbers": len(self.groups_joined)}})

    async def disconnect(self, code):
        for group in getattr(self, "groups_joined", []):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def inbox_event(self, message):
        await self.send_json({"event": message["event"], "data": message["data"]})

    @database_sync_to_async
    def _number_groups(self, user):
        groups = [group_for_number(pk) for pk in user.visible_numbers.values_list("pk", flat=True)]
        # Plus a channel of their own, for anything addressed to this agent
        # rather than to everyone watching a number.
        groups.append(group_for_agent(user.pk))
        # Admins also hear what belongs to no number, such as an agent with
        # nothing assigned asking for access.
        if user.has_admin_rights:
            groups.append(group_for_admins())
        return groups
