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
        if message.get("event") == "leadai.access.changed":
            await self._rejoin()

    async def _rejoin(self):
        """A Lead AI grant of this agent changed (apps/leadai/access.py): the open socket's groups follow it, so the
        agent hears the desk from now on, or stops hearing it, without a reload."""
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            return
        wanted = await self._fresh_groups(user)
        joined = set(getattr(self, "groups_joined", []))
        for group in set(wanted) - joined:
            await self.channel_layer.group_add(group, self.channel_name)
        for group in joined - set(wanted):
            await self.channel_layer.group_discard(group, self.channel_name)
        self.groups_joined = wanted

    @database_sync_to_async
    def _number_groups(self, user):
        return self._groups_for(user)

    @database_sync_to_async
    def _fresh_groups(self, user):
        """The groups for the agent's row as it is now, not the socket's copy of it (a grant may have changed it)."""
        from django.contrib.auth import get_user_model

        fresh = get_user_model().objects.filter(pk=user.pk).first()
        return self._groups_for(fresh) if fresh is not None and fresh.is_active else []

    def _groups_for(self, user):
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
        # The Lead AI desk (apps/leadai/lane.py): an agent with Lead AI access hears every Lead AI chat.
        from apps.leadai.lane import desk_groups

        groups.extend(desk_groups(user))
        return groups
