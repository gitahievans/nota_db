from django.shortcuts import render
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import PDFFile
from .serializers import PDFFileSerializer

class PDFUploadView(APIView):
    def post(self, request):
        serializer = PDFFileSerializer(data=request.data)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class PDFListView(APIView):
    def get (self, request):
        files = PDFFIle.objects.all()
        serializer = PDFSerializer(files, many=True)
        return Response(serializer.data)
    
class PDFDownloadView(APIView):
    def get(self, request, pk):
        pdf = get_object_or_404(PDFFile, pk=kp)
        response = HtttpResponse(pdf.pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachemnt; filename="{pdf.title}.pdf"'
        return response