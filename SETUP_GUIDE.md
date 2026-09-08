# Media Upload Module - Setup Guide

## 1. Install Dependencies

Add to `requirements.txt`:

```
boto3>=1.26.0
```

If not already present in your requirements.txt, also ensure:

```
djangorestframework>=3.14.0
django>=4.2.0
```

Install:
```bash
pip install -r requirements.txt
```

## 2. Run Migrations

```bash
python manage.py migrate
```

This will apply:
- `0002_alter_activityimage_image_data` - Changes ActivityImage.image_data from ImageField to JSONField
- `0002_alter_student_image_data` - Changes Student.image_data from TextField to JSONField
- `0001_initial` for uploads app (empty migrations, no tables created)

## 3. Configure Environment Variables

Add to your `.env` file:

```env
# For development (use local storage)
STORAGE_TYPE=local
SITE_URL=http://localhost:8000

# For production (use R2)
STORAGE_TYPE=r2
R2_BUCKET_NAME=classping-media
R2_ACCOUNT_ID=your_account_id
R2_ACCESS_KEY_ID=your_access_key
R2_SECRET_ACCESS_KEY=your_secret_key
R2_REGION=auto
SITE_URL=https://api.classping.com
```

## 4. Verify Configuration

```bash
# Test R2 connection (optional)
python manage.py shell
>>> from apps.uploads.storage import get_storage
>>> storage = get_storage()
>>> print(storage)  # Should show R2Storage or LocalStorage
```

## 5. Update Existing Models (if needed)

The following models are already updated:
- ✅ `ActivityImage` - Now uses JSONField + MediaFieldMixin
- ✅ `Student` - Now uses JSONField + MediaFieldMixin

For other models with media fields, apply the same pattern (see documentation).

## 6. API Documentation

**Presign URL** (Get upload permission):
```bash
curl -X POST http://localhost:8000/api/media/presign/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "logo.png",
    "content_type": "image/png",
    "expires_in": 3600
  }'
```

**Complete Upload** (Finalize after client uploads to R2):
```bash
curl -X POST http://localhost:8000/api/media/2025/01/15/abc123.png/complete/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "file_size": 12345
  }'
```

## 7. Model Usage

```python
# In your views
activity_image = ActivityImage.objects.first()

# Access metadata
metadata = activity_image.image_data
# Returns: {"id": "...", "storage": "r2", "metadata": {...}}

# Access URL
url = activity_image.image_url
# Returns: "https://bucket.r2.cloudflarestorage.com/2025/01/15/abc123.png"

# In serializers
class ActivityImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActivityImage
        fields = ['id', 'image_data', 'image_url', ...]
```

## 8. Testing Locally

```bash
# Run tests
python manage.py test apps.uploads

# Interactive testing
python manage.py shell
>>> from apps.uploads.services.media import MediaService
>>> result = MediaService.generate_presign_url('test.png', 'image/png')
>>> print(result)
```

## 9. File Structure After Setup

```
apps/
  uploads/                    ← NEW MODULE
    __init__.py
    apps.py
    storage.py               ← Storage backend abstraction
    services/
      __init__.py
      media.py              ← Media operations service
    views.py                ← API endpoints
    serializers.py          ← DRF serializers
    urls.py                 ← URL routing
    utils.py                ← MediaFieldMixin
    migrations/
      __init__.py
      0001_initial.py
  
  activities/
    models.py               ← ActivityImage updated with MediaFieldMixin
    serializers.py          ← Added image_url field
    ...
  
  students/
    models.py               ← Student updated with MediaFieldMixin
    serializers.py          ← Added image_url field
    ...

config/
  settings.py               ← Added R2 config + media settings
  urls.py                   ← Added uploads URLs

MEDIA_UPLOAD_ARCHITECTURE.md  ← Comprehensive documentation
```

## 10. Troubleshooting

**Can't find migrations?**
- Check that `apps/uploads/migrations/__init__.py` exists
- Run: `python manage.py showmigrations uploads`

**Import errors?**
- Ensure `apps.uploads.apps.UploadsConfig` is in `INSTALLED_APPS` in settings.py
- Verify all files are created (check via file explorer)

**R2 connection fails?**
- Verify credentials in `.env`
- Check bucket exists in R2 console
- Test IAM permissions: `s3:GetObject`, `s3:PutObject`, `s3:HeadObject`

**Presigned URL not working?**
- Check URL hasn't expired (`expires_in` default is 1 hour)
- Verify R2 bucket CORS settings allow PUT requests
- Ensure Content-Type header in client request matches presigned request

## 11. Quick Start Example (Frontend/Client)

```javascript
// 1. Get presigned URL
const presignResponse = await fetch('http://localhost:8000/api/media/presign/', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    filename: 'profile.png',
    content_type: 'image/png'
  })
});

const { file_key, presigned_url } = await presignResponse.json();

// 2. Upload file directly to R2
const uploadResponse = await fetch(presigned_url, {
  method: 'PUT',
  headers: {
    'Content-Type': 'image/png'
  },
  body: file
});

// 3. Complete upload
const completeResponse = await fetch(
  `http://localhost:8000/api/media/${file_key}/complete/`,
  {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      file_size: file.size
    })
  }
);

const mediaMetadata = await completeResponse.json();

// 4. Save metadata to model
// POST to your Activity/Student endpoint with:
// image_data: mediaMetadata
```

---

For detailed architecture documentation, see: [MEDIA_UPLOAD_ARCHITECTURE.md](./MEDIA_UPLOAD_ARCHITECTURE.md)
