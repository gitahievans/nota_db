from django.urls import path
from .views import (
    PDFUploadView,
    PDFListView,
    PDFDownloadView,
    CategoryListView,
    UpdatePDFView,
    PDFFileDetailView,
    ServeMIDIView,
    ServeMusicXMLView,
    GenerateSummaryView
)

urlpatterns = [
    path("files/", PDFListView.as_view(), name="pdf-list"),
    path("upload/", PDFUploadView.as_view(), name="pdf-upload"),
    path("download/<int:pk>/download", PDFDownloadView.as_view(), name="pdf-download"),
    path("categories/", CategoryListView.as_view(), name="category-list"),
    path("update/<int:pk>/", UpdatePDFView.as_view(), name="pdf-update"),
    path("scores/<int:pk>/", PDFFileDetailView.as_view(), name="pdf-detail"),
    path(
        "serve-musicxml/<int:score_id>/",
        ServeMusicXMLView.as_view(),
        name="serve_musicxml",
    ),
    path("serve-midi/<int:score_id>/", ServeMIDIView.as_view(), name="serve_midi"),
    path("generate-summary/", GenerateSummaryView.as_view(), name="generate_summary"),
]
