"""Remove stored media when its owning database value is removed or replaced."""
import logging

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.db import transaction

from apps.uploads.services.media import MediaService
from apps.uploads.utils import MediaFieldMixin
from apps.uploads.references import MEDIA_MODELS, is_media_referenced

logger = logging.getLogger(__name__)



def _key(value):
    data = MediaFieldMixin._parse_media_data(value)
    if not data:
        return None
    return data.get("id") or data.get("object_key")


def _delete(key):
    if not key:
        return
    try:
        if not is_media_referenced(key):
            MediaService.delete_object(key)
    except Exception:
        # Storage cleanup must not turn a successful database deletion into a 500.
        logger.exception("Unable to delete media object %s", key)


def _model(sender):
    return sender._meta.label


for label in MEDIA_MODELS:
    # Resolve lazily so app loading does not create import-order problems.
    from django.apps import apps
    model = apps.get_model(label)
    if model is None:
        continue

    @receiver(pre_save, sender=model, weak=False)
    def remember_old_media(sender, instance, **kwargs):
        if not instance.pk:
            instance._old_media_key = None
            return
        old = sender.objects.filter(pk=instance.pk).values_list("image_data", flat=True).first()
        instance._old_media_key = _key(old)

    @receiver(post_save, sender=model, weak=False)
    def delete_replaced_media(sender, instance, **kwargs):
        old_key = getattr(instance, "_old_media_key", None)
        new_key = _key(getattr(instance, "image_data", None))
        if new_key:
            def mark_attached(key=new_key):
                try:
                    MediaService.mark_upload_attached(key)
                except Exception:
                    logger.exception("Unable to clear pending upload %s", key)
            transaction.on_commit(mark_attached, using=kwargs.get("using"))
        if old_key and old_key != new_key:
            transaction.on_commit(lambda key=old_key: _delete(key), using=kwargs.get("using"))

    @receiver(post_delete, sender=model, weak=False)
    def delete_model_media(sender, instance, **kwargs):
        key = _key(getattr(instance, "image_data", None))
        transaction.on_commit(lambda: _delete(key), using=kwargs.get("using"))
