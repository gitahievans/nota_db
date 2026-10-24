from django.db import models
from storages.backends.s3boto3 import S3Boto3Storage
from django.contrib.postgres.fields import JSONField


class PDFFileStorage(S3Boto3Storage):
    location = "nota-pdfs"


class Category(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Category"
        verbose_name_plural = "Categories"


class PDFFile(models.Model):
    SOURCE_TYPE_PDF = "pdf"
    SOURCE_TYPE_IMAGE = "image"
    SOURCE_TYPE_AUDIO = "audio"
    SOURCE_TYPE_CHOICES = [
        (SOURCE_TYPE_PDF, "PDF"),
        (SOURCE_TYPE_IMAGE, "Image"),
        (SOURCE_TYPE_AUDIO, "Audio"),
    ]

    title = models.CharField(max_length=100)
    lyrics = models.TextField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    file = models.FileField(upload_to="", storage=PDFFileStorage(), blank=True)
    composer = models.CharField(
        max_length=100, blank=False, null=False, default="Anonymous"
    )
    year = models.IntegerField(null=True, blank=True)
    categories = models.ManyToManyField(Category, related_name="pdffiles", blank=True)
    results = models.JSONField(null=True, blank=True)
    processed = models.BooleanField(default=False, blank=True, null=True)
    musicxml_url = models.URLField(max_length=2000, null=True, blank=True)
    midi_url = models.URLField(max_length=2000, null=True, blank=True)
    analysis_task_id = models.CharField(max_length=255, null=True, blank=True, editable=False)
    job_state = models.CharField(max_length=20, default="", blank=True, editable=False)
    job_stage = models.CharField(max_length=64, default="", blank=True, editable=False)
    job_updated_at = models.DateTimeField(null=True, blank=True, editable=False)
    summary = models.TextField(null=True, blank=True)
    # Empty historical ownership is deliberately not inferred from source_type.
    retention_kind = models.CharField(max_length=16, default="legacy", editable=False, db_index=True)
    terminal_at = models.DateTimeField(null=True, blank=True, editable=False)
    expires_at = models.DateTimeField(null=True, blank=True, editable=False, db_index=True)
    deletion_pending = models.BooleanField(default=False, editable=False)
    source_type = models.CharField(
        max_length=10,
        choices=SOURCE_TYPE_CHOICES,
        default=SOURCE_TYPE_PDF,
    )

    def __str__(self):
        return f"{self.title} - {self.composer}"

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "PDF File"
        verbose_name_plural = "PDF Files"
