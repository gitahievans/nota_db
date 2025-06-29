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
from celery.result import AsyncResult
from rest_framework.views import APIView
import boto3
from django.conf import settings
from django.http import HttpResponse, FileResponse
from django.views import View
from django_ai_assistant import AIAssistant
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from django.http import JsonResponse
import json
import os
from google.generativeai import GenerativeModel, configure

logger = logging.getLogger(__name__)


class PDFUploadView(APIView):
    def post(self, request):
        serializer = PDFFileSerializer(data=request.data)
        logger.info(f"Incoming data: {request.data}")
        if serializer.is_valid():
            logger.info("Serializer is valid")
            analyze = request.data.get("analyze", "false").lower() == "true"
            pdf_file = request.FILES.get("pdf_file")
            if not pdf_file and analyze:
                logger.error("No PDF file provided for analysis")
                return Response(
                    {"error": "PDF file is required for analysis"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if analyze:
                score = serializer.save(pdf_file=None)  # Temporarily skip file field
                temp_dir = settings.TEMP_STORAGE_DIR / str(score.id)
                temp_dir.mkdir(parents=True, exist_ok=True)
                temp_path = temp_dir / "input.pdf"
                logger.info(f"Saving PDF to {temp_path}")
                try:
                    with open(temp_path, "wb") as f:
                        for chunk in pdf_file.chunks():
                            f.write(chunk)
                    score.pdf_file.name = None  # Clear the name to avoid saving
                    score.save()  # Save again to update pdf_file
                    logger.info(f"PDF saved to {temp_path}, pdf_file field cleared")
                except Exception as e:
                    logger.error(f"Failed to save PDF to {temp_path}: {str(e)}")
                    return Response(
                        {"error": f"Failed to save PDF: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
            else:
                score = serializer.save()  # Use PDFFileStorage for R2

            logger.info(f"Uploaded score ID: {score.id}")
            task_id = None
            if analyze:
                task = process_score.delay(score.id)
                task_id = task.id
            return Response(
                {
                    "status": "success",
                    "score_id": score.id,
                    "task_id": task_id,
                    "message": "PDF uploaded"
                    + (" and processing started" if analyze else ""),
                },
                status=status.HTTP_201_CREATED,
            )
        logger.error(f"Upload failed: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class GenerateSummaryView(APIView):
    def post(self, request):
        # Log raw request body for debugging
        logger.debug(f"Raw request body: {request.body}")

        # Safely parse JSON
        try:
            data = request.data
            score_id = data.get("score_id")
        except ValueError as e:
            logger.error(f"JSON parse error: {str(e)}")
            return JsonResponse(
                {"error": f"Invalid JSON: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST
            )

        if not score_id:
            logger.error("No score_id provided in request")
            return JsonResponse(
                {"error": "score_id is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            score = PDFFile.objects.get(id=score_id)
        except PDFFile.DoesNotExist:
            logger.error(f"PDFFile with id {score_id} not found")
            return JsonResponse(
                {"error": f"Score with id {score_id} not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not score.processed or not score.results:
            logger.error(f"Score {score_id} not processed or results missing")
            return JsonResponse(
                {"error": "Score is not processed or analysis results are missing"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Parse Music21 results
            results = score.results
            if isinstance(results, str):
                results = json.loads(results)

            # Initialize Gemini API
            configure(api_key=os.getenv("GEMINI_API_KEY"))  # Use environment variable
            model = GenerativeModel("gemini-2.5-flash")

            # Format prompt as a single string
            results_str = json.dumps(results, indent=2)
            prompt = (
                f"Generate a concise summary of a music score titled '{score.title}' by {score.composer}. "
                f"The analysis results are:\n{results_str}\n"
                f"Include insights on musical style, structure, and historical context."
            )

            # Generate summary using Gemini
            try:
                response = model.generate_content(prompt)
                summary = response.text
            except Exception as e:
                logger.error(f"Gemini API call failed: {str(e)}")
                raise

            # Save summary to PDFFile
            score.summary = summary
            score.save()
            logger.info(f"Generated and saved summary for score {score_id}")

            return JsonResponse(
                {"status": "success", "score_id": score_id, "summary": summary},
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(f"Failed to generate summary for score {score_id}: {str(e)}")
            return JsonResponse(
                {"error": f"Failed to generate summary: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ServeMusicXMLView(View):
    def get(self, request, score_id):
        score = get_object_or_404(PDFFile, pk=score_id)
        file_path = settings.TEMP_STORAGE_DIR / f"{score.id}/output.xml"
        if not file_path.exists():
            logger.error(f"MusicXML file not found at {file_path}")
            return HttpResponse(status=404, content="MusicXML file not found")

        try:
            return FileResponse(
                open(file_path, "rb"),
                content_type="application/vnd.recordare.musicxml+xml",
                as_attachment=False,
            )
        except Exception as e:
            logger.error(f"Error serving MusicXML file: {str(e)}")
            return HttpResponse(status=500, content="Internal server error")


class ServeMIDIView(View):
    def get(self, request, score_id):
        score = get_object_or_404(PDFFile, id=score_id)
        file_path = settings.TEMP_STORAGE_DIR / f"{score_id}/{score.id}.mid"
        if not file_path.exists():
            logger.error(f"MIDI file not found at {file_path}")
            return HttpResponse(status=404, content="MIDI file not found")
        try:
            return FileResponse(
                open(file_path, "rb"),
                content_type="audio/midi",
                as_attachment=False,
            )
        except Exception as e:
            logger.error(f"Failed to serve MIDI for score {score_id}: {str(e)}")
            return HttpResponse(status=500, content=f"Error serving file: {str(e)}")


class PDFListView(APIView):
    def get(self, request):
        files = PDFFile.objects.all()
        serializer = PDFFileSerializer(files, many=True)
        return Response(serializer.data)


class PDFFileDetailView(APIView):
    def get(self, request, pk):
        try:
            score = PDFFile.objects.get(pk=pk)
            serializer = PDFFileSerializer(score)
            task_id = request.query_params.get("task_id")
            task_status = None
            if task_id:
                task = AsyncResult(task_id)
                task_status = {
                    "state": task.state,
                    "info": task.info if task.info else None,
                }
            logger.info(f"Score {pk} serialized data: {serializer.data}")
            logger.info(f"Task status for score {pk}: {task_status}")
            return Response(
                {"score": serializer.data, "task_status": task_status},
                status=status.HTTP_200_OK,
            )
        except PDFFile.DoesNotExist:
            logger.error(f"Score ID {pk} not found")
            return Response(
                {"error": f"Score ID {pk} not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error retrieving score ID {pk}: {str(e)}")
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PDFDownloadView(APIView):
    def get(self, request, pk):
        pdf = get_object_or_404(PDFFile, pk=pk)
        response = HttpResponse(pdf.pdf_file, content_type="application/pdf")
        response["Content-Disposition"] = f'attachemnt; filename="{pdf.title}.pdf"'
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
