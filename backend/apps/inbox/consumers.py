from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .events import group_for_admins, group_for_agent, group_for_number
from .visibility import sees_all_inbox_chats


class InboxConsumer(AsyncJsonWebsocketConsumer):
    """Streams inbox activity for chats this agent may open."""

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
        groups = [group_for_agent(user.pk)]
        # Number groups carry every chat on the line. Only panel admins join
        # them; everyone else hears their own assigned threads on the agent
        # channel so a colleague's inbound does not appear in the list.
        if sees_all_inbox_chats(user):
            groups.extend(
                group_for_number(pk) for pk in user.visible_numbers.values_list("pk", flat=True)
            )
        if user.has_admin_rights:
            groups.append(group_for_admins())
        return groups
