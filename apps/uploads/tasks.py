from celery import shared_task


@shared_task
def delete_reset_media_task(keys):
    """Delete files cleared by a storage reset (see services.quota.reset_branch_media)."""
    from apps.uploads.services.quota import delete_reset_files

    return delete_reset_files(keys)
