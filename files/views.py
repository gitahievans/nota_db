from django.shortcuts import render
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import PDFFile, Category
from .serializers import CategorySerializer
from .serializers import PDFFileSerializer
from django.http import HttpResponse
import logging
from .tasks import process_score

logger = logging.getLogger(__name__)

class PDFUploadView(APIView):
    def post(self, request):
        serializer = PDFFileSerializer(data=request.data)
        print(f"incoming data {request.data}")
        if serializer.is_valid():
            print(f"serializer is valid")
            score = serializer.save()
            print(f"Uploaded score ID: {score.id}")
            process_score.delay(score.id)  
            return Response(
                {
                    "status": "success",
                    "score_id": score.id,
                    "message": "PDF uploaded and processing started"
                },
                status=status.HTTP_201_CREATED
            )
        logger.error(f"Upload failed: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class PDFListView(APIView):
    def get (self, request):
        files = PDFFile.objects.all()
        serializer = PDFFileSerializer(files, many=True)
        return Response(serializer.data)
    
class PDFDownloadView(APIView):
    def get(self, request, pk):
        pdf = get_object_or_404(PDFFile, pk=pk)
        response = HttpResponse(pdf.pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachemnt; filename="{pdf.title}.pdf"'
        return response
    
class CategoryListView(APIView):
    def get(self, request):
        categories = Category.objects.all()
        serializer = CategorySerializer(categories, many=True)
        return Response(serializer.data)
    
class UpdatePDFView(APIView):
    def put(self, request, pk):
        pdf = get_object_or_404(PDFFile, pk=pk)
        serializer = PDFFileSerializer(pdf, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)