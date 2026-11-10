from django.utils import timezone


def append_note(existing, note):
    """Add a timestamped line to a free-text note field (e.g. review_note)."""
    line = "[{}] {}".format(timezone.localtime().strftime("%Y-%m-%d %H:%M"), note)
    return "{}\n{}".format(existing, line).strip()
