from flask import Blueprint
from ariella_chat_clean import chat_clean

ariella_chat_v2 = Blueprint('ariella_chat_v2', __name__)

# Ariella has one conversation engine only.
# Questionnaire stages, missing-field logic and the legacy intake endpoint were
# intentionally removed. Structured trip data is extracted silently by
# Tinkerbell in ariella_chat_clean.py and must never choose the next question.

@ariella_chat_v2.post('/api/ariella/chat')
def ariella_chat_live():
    return chat_clean()


@ariella_chat_v2.post('/api/ariella/chat-clean')
def ariella_chat_clean_direct():
    return chat_clean()
