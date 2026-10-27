"""What the employee says first on an incoming call: the recording disclosure, then a greeting.

The opening is fixed text, not the model's choice: the caller hears the disclosure before anything
else, every time, in the employee's own language. The owner can reword it (and the greetings) in the
inbound settings but cannot switch the disclosure off.
"""

import re

from app.inbound.settings import PLACEHOLDER, InboundSettings

DISCLOSURE = {
    "en": "This call may be recorded for quality purposes.",
    "hi": "यह कॉल गुणवत्ता के लिए रिकॉर्ड की जा सकती है।",
    "te": "ఈ కాల్ నాణ్యత కోసం రికార్డ్ చేయబడవచ్చు.",
}
GREETING_NEW = {
    "en": "Hello, thank you for calling {{business_name}}. How can I help you?",
    "hi": "नमस्ते, {{business_name}} में आपका स्वागत है। मैं आपकी कैसे मदद करूँ?",
    "te": "నమస్కారం, {{business_name}}కు స్వాగతం. నేను మీకు ఎలా సహాయం చేయగలను?",
}
GREETING_RETURNING = {
    "en": "Hello {{name}}, good to hear from you again. How can I help you today?",
    "hi": "नमस्ते {{name}} जी, दोबारा कॉल करने के लिए धन्यवाद। मैं आपकी कैसे मदद करूँ?",
    "te": "నమస్కారం {{name}} గారు, మళ్ళీ కాల్ చేసినందుకు ధన్యవాదాలు. నేను మీకు ఎలా సహాయం చేయగలను?",
}
CLOSED = {
    "en": "Thank you for calling {{business_name}}. We are closed right now. Please tell me your "
    "name and your message, and we will get back to you.",
    "hi": "{{business_name}} में कॉल करने के लिए धन्यवाद। हम अभी बंद हैं। कृपया अपना नाम और संदेश "
    "बताइए, हम आपसे संपर्क करेंगे।",
    "te": "{{business_name}}కు కాల్ చేసినందుకు ధన్యవాదాలు. మేము ప్రస్తుతం మూసివేసి ఉన్నాము. దయచేసి "
    "మీ పేరు మరియు సందేశం చెప్పండి, మేము మిమ్మల్ని సంప్రదిస్తాము.",
}


def fill(text: str, **values: str) -> str:
    """Put the values in the {{placeholders}}; one the call has no value for becomes nothing."""
    filled = PLACEHOLDER.sub(lambda m: values.get(m.group(1), ""), text)
    return re.sub(r"\s+", " ", filled).strip()


def _pick(owner_text: str, defaults: dict[str, str], language: str) -> str:
    return owner_text.strip() or defaults.get(language, defaults["en"])


def opening(
    settings: InboundSettings,
    language: str,
    *,
    business_name: str,
    caller_name: str | None,
    returning: bool,
    closed: bool,
) -> str:
    """The disclosure, then the closed message, or the greeting for a returning lead (when we know
    their name) or a new caller."""
    values = {"business_name": business_name, "name": caller_name or ""}
    if closed:
        body = _pick(settings.closed_message, CLOSED, language)
    elif returning and caller_name:
        body = _pick(settings.greeting_returning, GREETING_RETURNING, language)
    else:
        body = _pick(settings.greeting_new, GREETING_NEW, language)
    disclosure = _pick(settings.disclosure, DISCLOSURE, language)
    return f"{fill(disclosure, **values)} {fill(body, **values)}"
