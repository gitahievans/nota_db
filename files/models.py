from django.db import models
from storages.backends.s3boto3 import S3Boto3Storage


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
    title = models.CharField(max_length=100)
    lyrics = models.TextField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    pdf_file = models.FileField(upload_to="", storage=PDFFileStorage(), blank=True)
    composer = models.CharField(
        max_length=100, blank=False, null=False, default="Anonymous"
    )
    year = models.IntegerField(null=True, blank=True)
    categories = models.ManyToManyField(Category, related_name="pdffiles", blank=True)

    def __str__(self):
        return f"{self.title} - {self.composer}"

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "PDF File"
        verbose_name_plural = "PDF Files"
