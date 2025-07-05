from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import PDFFile, Category
from .serializers import CategorySerializer
from .serializers import FileSerializer
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
from django.conf import settings
from google.generativeai import GenerativeModel, configure
import google.generativeai as genai
from PIL import Image, ImageEnhance
import cv2
import numpy as np

logger = logging.getLogger(__name__)


class FileUploadView(APIView):
    def preprocess_image_for_audiveris(self, image_path, target_dpi=300):
        """
        Preprocess image to improve Audiveris recognition.
        Target DPI of 300 is recommended by Audiveris.
        """
        try:
            # Read image with OpenCV for better processing
            img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            if img is None:
                # Fallback to PIL if OpenCV fails
                pil_img = Image.open(image_path)
                img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

            original_height, original_width = img.shape[:2]
            logger.info(
                f"Original image dimensions: {original_width}x{original_height}"
            )

            # Calculate current DPI estimate (assume typical sheet music is ~8.5" wide)
            estimated_width_inches = 8.5
            current_dpi = original_width / estimated_width_inches
            logger.info(f"Estimated current DPI: {current_dpi:.1f}")

            # Calculate scaling factor to achieve target DPI
            if current_dpi < target_dpi:
                scale_factor = target_dpi / current_dpi
                # Cap scaling to avoid excessive upscaling
                scale_factor = min(scale_factor, 3.0)

                new_width = int(original_width * scale_factor)
                new_height = int(original_height * scale_factor)

                logger.info(
                    f"Upscaling by factor {scale_factor:.2f} to {new_width}x{new_height}"
                )

                # Use INTER_CUBIC for upscaling (better quality)
                img = cv2.resize(
                    img, (new_width, new_height), interpolation=cv2.INTER_CUBIC
                )

            # Convert to grayscale
            if len(img.shape) == 3:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            else:
                gray = img

            # Apply slight Gaussian blur to reduce noise
            gray = cv2.GaussianBlur(gray, (3, 3), 0)

            # Enhance contrast using CLAHE (Contrast Limited Adaptive Histogram Equalization)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray = clahe.apply(gray)

            # Apply adaptive thresholding instead of simple binarization
            # This preserves more detail for Audiveris
            binary = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
            )

            # Optional: Apply morphological operations to clean up the image
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

            # Save the processed image
            cv2.imwrite(str(image_path), binary)

            final_height, final_width = binary.shape
            logger.info(
                f"Final processed image dimensions: {final_width}x{final_height}"
            )

            # Estimate interline spacing for validation
            # Typical interline spacing should be at least 15-20 pixels for good recognition
            estimated_interline = (
                final_height / 50
            )  # Rough estimate based on typical sheet music
            logger.info(
                f"Estimated interline spacing: {estimated_interline:.1f} pixels"
            )

            if estimated_interline < 15:
                logger.warning(
                    f"Estimated interline spacing ({estimated_interline:.1f}px) may be too low for reliable recognition"
                )

            return (
                True,
                f"Image processed successfully. Final size: {final_width}x{final_height}",
            )

        except Exception as e:
            logger.error(f"Image preprocessing failed: {str(e)}")
            return False, f"Image preprocessing failed: {str(e)}"

    def post(self, request):
        serializer = FileSerializer(data=request.data)
        logger.info(f"Incoming data: {request.data}")

        if serializer.is_valid():
            logger.info("Serializer is valid")
            analyze = request.data.get("analyze", "false").lower() == "true"
            uploaded_file = request.FILES.get("file")

            if not uploaded_file and analyze:
                logger.error("No file provided for analysis")
                return Response(
                    {"error": "File is required for analysis"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if analyze:
                score = serializer.save(file=None)
                temp_dir = settings.TEMP_STORAGE_DIR / str(score.id)
                temp_dir.mkdir(parents=True, exist_ok=True)
                file_ext = uploaded_file.name.split(".")[-1].lower()
                temp_path = temp_dir / f"input.{file_ext}"

                logger.info(f"Saving file to {temp_path}")
                try:
                    if file_ext in ["jpg", "jpeg", "png", "tiff", "tif"]:
                        # Save original file first
                        with open(temp_path, "wb") as f:
                            for chunk in uploaded_file.chunks():
                                f.write(chunk)

                        # Apply advanced preprocessing for images
                        success, message = self.preprocess_image_for_audiveris(
                            temp_path
                        )
                        if not success:
                            logger.error(f"Image preprocessing failed: {message}")
                            return Response(
                                {"error": f"Image preprocessing failed: {message}"},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            )
                        logger.info(f"Image preprocessing completed: {message}")

                    elif file_ext == "pdf":
                        # PDF processing remains unchanged
                        with open(temp_path, "wb") as f:
                            for chunk in uploaded_file.chunks():
                                f.write(chunk)
                    else:
                        logger.error(f"Unsupported file format: {file_ext}")
                        return Response(
                            {"error": f"Unsupported file format: {file_ext}"},
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                    score.file = None
                    score.save()
                    logger.info(f"File saved to {temp_path}, file field cleared")

                except Exception as e:
                    logger.error(
                        f"Failed to save/process file to {temp_path}: {str(e)}"
                    )
                    return Response(
                        {"error": f"Failed to save/process file: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
            else:
                score = serializer.save()

            logger.info(f"Uploaded score ID: {score.id}")
            task_id = None
            if analyze:
                task = process_score.delay(score.id, file_ext=file_ext)
                task_id = task.id

            return Response(
                {
                    "status": "success",
                    "score_id": score.id,
                    "task_id": task_id,
                    "message": f"{'Image' if file_ext != 'pdf' else 'PDF'} uploaded"
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

            logger.debug("Configuring Gemini API")
            genai.configure(api_key="AIzaSyAJvW7orvp0K-_bDkQ3Ffr34IvwSd3kQ0g")
            model = GenerativeModel("gemini-2.5-flash")

            # Extract key values upfront for cleaner prompt formatting and reliability
            results_str = json.dumps(results, indent=2)
            key_signature = results.get("key", "not detected")
            time_signature = results.get("time_signature", "not specified")

            # Extract score structure information
            score_structure = results.get("score_structure", {})
            score_type = score_structure.get("score_type", "unknown")
            ensemble_type = score_structure.get("ensemble_type", "not specified")

            # Extract notable elements for preview
            notable_elements = results.get("notable_elements", {})
            accidentals = notable_elements.get("accidentals", {})
            articulations = notable_elements.get("articulations", {})
            dynamics = notable_elements.get("dynamics", {})

            # Create summary of key findings
            key_findings = []
            if accidentals.get("has_accidentals"):
                key_findings.append("accidentals")
            if articulations.get("staccato", {}).get("has_staccato"):
                key_findings.append("staccato")
            if articulations.get("accent", {}).get("has_accent"):
                key_findings.append("accents")
            if articulations.get("tenuto", {}).get("has_tenuto"):
                key_findings.append("tenuto")
            if dynamics.get("has_dynamics"):
                key_findings.append("dynamics")

            # Format prompt with direct data references
            prompt = (
                f"You are a music theory expert explaining '{score.title}' by {score.composer or 'Unknown'} "
                f"to a music theory beginner using Music21 analysis results.\n\n"
                f"Key musical elements detected:\n"
                f"- Key signature: {key_signature}\n"
                f"- Time signature: {time_signature}\n"
                f"- Ensemble type: {ensemble_type}\n"
                f"- Score type: {score_type}\n"
                f"- Notable features found: {', '.join(key_findings) if key_findings else 'Basic elements only'}\n\n"
                f"Full analysis data:\n{results_str}\n\n"
                f"Your primary goal is to explain the Music21 analysis results in a clear, concise, and beginner-friendly way. Focus on:\n\n"
                f"1. **Explain Key Elements**: Describe the key signature ({key_signature}), time signature ({time_signature}), "
                f"ensemble type ({ensemble_type}), and any chord progressions detected. Clarify what these terms mean and their role in the music.\n\n"
                f"2. **Highlight Notable Features**: The analysis detected these notable elements: {', '.join(key_findings) if key_findings else 'none'}. "
                f"For each present element, explain what it is, how it affects the music, and why it might be challenging for a beginner.\n\n"
                f"3. **Address Beginner Challenges**: Identify elements that might be confusing for new learners "
                f"(e.g., unusual time signatures, frequent accidentals, specific articulations) and provide simple explanations.\n\n"
                f"4. **Contextual Insights (Secondary)**: Briefly comment on the musical style or structure, "
                f"but only after explaining the analysis results.\n\n"
                f"Keep the explanation concise (150-200 words), avoid jargon unless explained, and ensure the tone is "
                f"encouraging and educational for a beginner. Focus on the meaningful musical content and ignore visualization data."
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
        serializer = FileSerializer(files, many=True)
        return Response(serializer.data)


class PDFFileDetailView(APIView):
    def get(self, request, pk):
        try:
            score = PDFFile.objects.get(pk=pk)
            serializer = FileSerializer(score)
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
        serializer = FileSerializer(pdf, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
