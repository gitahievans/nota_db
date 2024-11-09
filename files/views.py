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

class PDFUploadView(APIView):
    def post(self, request):
        serializer = PDFFileSerializer(data=request.data)
        print(request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
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