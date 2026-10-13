"""The Lead AI assistant: converses with customers in Lead AI chats.

Only chats on the Lead AI screen are answered, with the Lead AI's own OpenAI
key (settings.LEADAI_OPENAI_API_KEY). The model proposes; code decides: an
appointment is booked only after hours.py accepts its date and time.
"""
