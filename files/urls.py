from django.urls import path
from .views import PDFUploadView, PDFListView, PDFDownloadView

urlpatterns = [
    path('files/', PDFListView.as_view(), name='pdf-list'),
    path('upload/', PDFUploadView.as_view(), name='pdf-upload'),
    path('download/<int:pk>/download', PDFDownloadView.as_view(), name='pdf-download'),
]