from django.db import models
from storages.backends.s3boto3 import S3Boto3Storage


class PDFFileStorage(S3Boto3Storage):
    location = "nota-pdfs"


class PDFFile(models.Model):
    title = models.CharField(max_length=100)
    description = models.TextField()
    uploaded_at = models.DateTimeField(auto_now_add=True)
    pdf_file = models.FileField(upload_to="", storage=PDFFileStorage(), blank=True)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "PDF File"
        verbose_name_plural = "PDF Files"
