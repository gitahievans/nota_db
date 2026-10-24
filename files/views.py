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
import mimetypes
from django.conf import settings
from google.generativeai import GenerativeModel, configure
import google.generativeai as genai
from PIL import Image, ImageEnhance
import cv2
import numpy as np
from .text_extraction import TextExtractor
from .serializers import detect_source_type
from django.utils import timezone
from .outcomes import read_results, outcome, finalize, has_error
from .jobs import task_status as score_task_status, fail_job
from .lifecycle import operation_scope, hold_upload, session_view, lifetime, visible_score, unavailable

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

    @operation_scope
    def post(self, request):
        serializer = FileSerializer(data=request.data)
        logger.info(f"Incoming data: {request.data}")

        if serializer.is_valid():
            logger.info("Serializer is valid")
            analyze = request.data.get("analyze", "false").lower() == "true"
            uploaded_file = request.FILES.get("file")
            file_ext = None
            source_type = None

            if not uploaded_file and analyze:
                logger.error("No file provided for analysis")
                return Response(
                    {"error": "File is required for analysis"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if uploaded_file:
                file_ext = uploaded_file.name.split(".")[-1].lower()
                source_type = detect_source_type(uploaded_file.name)

            if analyze:
                score = serializer.save(
                    file=None,
                    source_type=source_type or PDFFile.SOURCE_TYPE_PDF,
                    job_state="QUEUED", job_stage="SAVING_INPUT", job_updated_at=timezone.now(),
                    retention_kind="analysis",
                )
                hold_upload(score)
                temp_dir = settings.TEMP_STORAGE_DIR / str(score.id)
                temp_path = temp_dir / f"input.{file_ext}"

                logger.info(f"Saving file to {temp_path}")
                try:
                    temp_dir.mkdir(parents=True, exist_ok=True)
                    if file_ext in ["jpg", "jpeg", "png", "tiff", "tif", "webp"]:
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
                            fail_job(score, "PREPROCESSING_IMAGE", "image_preprocessing_failed")
                            return Response(
                                {"error": "Image preprocessing failed.", "score_id": score.id},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            )
                        logger.info(f"Image preprocessing completed: {message}")

                    elif file_ext == "pdf":
                        # PDF processing remains unchanged
                        with open(temp_path, "wb") as f:
                            for chunk in uploaded_file.chunks():
                                f.write(chunk)
                    elif source_type == PDFFile.SOURCE_TYPE_AUDIO:
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
                    fail_job(score, "SAVING_INPUT", "input_save_failed")
                    return Response(
                        {"error": "Uploaded input could not be saved.", "score_id": score.id},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
            else:
                score = serializer.save(
                    source_type=source_type or PDFFile.SOURCE_TYPE_PDF, retention_kind="catalog"
                )

            if analyze:
                if source_type == PDFFile.SOURCE_TYPE_AUDIO:
                    extracted_text = {"status": "not_applicable", "message": "Text extraction is not applicable to audio uploads."}
                else:
                    try:
                        extracted_text = TextExtractor().extract_from_file(temp_path, file_ext)
                    except Exception:
                        logger.exception("Optional text extraction failed")
                        extracted_text = {"error": "Text extraction could not be completed."}
                # Persist optional OCR independently; failure to write its sidecar cannot stop dispatch.
                from .outcomes import redact_errors
                extracted_text = redact_errors(extracted_text)
                score.results = {"text_content": extracted_text}
                score.save(update_fields=["results"])
                try:
                    with open(temp_dir / "text_results.json", "w", encoding="utf-8") as f:
                        json.dump(extracted_text, f, ensure_ascii=False, indent=2)
                except Exception:
                    logger.exception("Optional text sidecar could not be written; database copy retained")

            logger.info(f"Uploaded score ID: {score.id}")
            task_id = None
            if analyze:
                score.job_state = "QUEUED"
                score.job_stage = "QUEUED"
                score.job_updated_at = timezone.now()
                score.save(update_fields=["job_state", "job_stage", "job_updated_at"])
                try:
                    task = process_score.delay(score.id, file_ext=file_ext, source_type=source_type or score.source_type)
                    task_id = task.id
                    PDFFile.objects.filter(pk=score.id, analysis_task_id__isnull=True).update(analysis_task_id=task_id)
                except Exception:
                    logger.exception("Score dispatch failed")
                    fail_job(score, "DISPATCHING", "dispatch_failed")
                    return Response({"error": "Processing could not be started.", "score_id": score.id}, status=503)

            if uploaded_file:
                if source_type == PDFFile.SOURCE_TYPE_AUDIO:
                    upload_label = "Audio file"
                elif source_type == PDFFile.SOURCE_TYPE_IMAGE:
                    upload_label = "Image"
                else:
                    upload_label = "PDF"
            else:
                upload_label = "Record"

            return Response(
                {
                    "status": "success",
                    "score_id": score.id,
                    "task_id": task_id,
                    "lifetime": lifetime(score),
                    "message": f"{upload_label} uploaded"
                    + (" and processing started" if analyze else ""),
                },
                status=status.HTTP_201_CREATED,
            )

        logger.error(f"Upload failed: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class GenerateSummaryView(APIView):
    @session_view(mutating=True)
    def post(self, request):
        score_id = request.data.get("score_id")
        if not score_id:
            return JsonResponse({"error": "score_id is required"}, status=400)
        score = get_object_or_404(PDFFile, pk=score_id)
        results = read_results(score.results)
        allowed = ("key", "key_analysis", "time_signature", "tempo", "tempo_analysis", "harmony",
                   "chords", "parts", "notable_elements", "score_structure", "accidental_observations")
        findings = {k: results[k] for k in allowed if k in results and results[k] and not has_error(results[k])}
        if not score.processed or not findings:
            return JsonResponse({"error": "No usable analysis findings are available for a summary."}, status=400)
        text = results.get("text_content", {})
        has_text = isinstance(text, dict) and not has_error(text) and bool(text.get("other_text"))
        summary_input = dict(findings, provenance={
            "source_type": score.source_type,
            "notation_quality": results.get("artifacts", {}).get("notation_quality", "unverified"),
            "audio_transcription": results.get("audio_transcription"),
        }, component_outcomes=results.get("processing", {}).get("components", {}))
        prompt = (
            "Explain these usable score findings to a beginner in 150-200 words. "
            "Written signatures and separate tonal estimate must remain distinct. "
            "Do not claim a progression, modulation, harmonic function or calibrated confidence. "
            "Pitch alterations are not counts of printed accidentals. Sonority labels are tentative. "
            "Audio draft signatures and tempo are inferred, not observed in the recording. "
            "Respect component absence, failure and uncertainty; never fill missing findings with guesses.\n"
            + json.dumps(summary_input, ensure_ascii=False)
        )
        if has_text:
            prompt += ("\nClean readable OCR text, omitting gibberish. Append it after --- EXTRACTED TEXT ---: "
                       + json.dumps(text["other_text"], ensure_ascii=False))
        try:
            if not settings.GEMINI_API_KEY:
                raise RuntimeError("Summary service is not configured")
            genai.configure(api_key=settings.GEMINI_API_KEY)
            response = GenerativeModel("gemini-2.5-flash").generate_content(
                prompt, request_options={"timeout": 60, "retry": None})
            full_response = response.text
            if not isinstance(full_response, str) or not full_response.strip():
                raise ValueError("Empty summary")
            summary, marker, cleaned_text = full_response.partition("--- EXTRACTED TEXT ---")
            if not summary.strip():
                raise ValueError("Empty summary")
            if marker and has_text and cleaned_text.strip():
                results["text_content"]["cleaned_text"] = cleaned_text.strip()
            score.summary = summary.strip()
            summary_outcome = outcome("success", "GENERATING_SUMMARY", "summary_available", "Optional summary is available.", ["summary"])
        except Exception:
            logger.exception("Optional summary failed for score %s", score_id)
            summary_outcome = outcome("failed", "GENERATING_SUMMARY", "summary_failed", "Optional summary could not be generated.", ["summary"] if score.summary else [])
        # Legacy payloads stay readable; no artifact regeneration is needed.
        results.setdefault("processing", {}).setdefault("components", {})["summary"] = summary_outcome
        if results.get("schema_version") == 2:
            score.results = finalize(score, results, refresh_artifacts=False)
            if score.job_state in {"SUCCESS", "FAILURE"}:
                score.job_stage = "PARTIAL" if score.results["processing"]["status"] == "partial" else "COMPLETED" if score.processed else "FAILED"
        else:
            results["processing"]["schema_version"] = 1
            score.results = results
        if not visible_score(score.pk):
            return unavailable()
        score.save(update_fields=["summary", "results", "job_stage"])
        if summary_outcome["status"] == "failed":
            return JsonResponse({"error": summary_outcome["message"], "code": "summary_failed"}, status=503)
        response_data = {"status": "success", "score_id": score.id, "summary": score.summary}
        if marker and has_text and cleaned_text.strip():
            response_data["cleaned_text"] = cleaned_text.strip()
        return JsonResponse(response_data, status=200)


class ServeMusicXMLView(View):
    @session_view()
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
        except FileNotFoundError:
            return unavailable()
        except Exception as e:
            logger.error(f"Error serving MusicXML file: {str(e)}")
            return HttpResponse(status=500, content="Internal server error")


class ServeMIDIView(View):
    @session_view()
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
        except FileNotFoundError:
            return unavailable()
        except Exception as e:
            logger.error(f"Failed to serve MIDI for score {score_id}: {str(e)}")
            return HttpResponse(status=500, content="Artifact could not be served.")


class ServePreviewMIDIView(View):
    @session_view()
    def get(self, request, score_id):
        file_path = settings.TEMP_STORAGE_DIR / f"{score_id}/preview.mid"
        if not file_path.exists():
            logger.error(f"Preview MIDI file not found at {file_path}")
            return HttpResponse(status=404, content="Preview MIDI file not found")
        try:
            return FileResponse(
                open(file_path, "rb"),
                content_type="audio/midi",
                as_attachment=False,
            )
        except FileNotFoundError:
            return unavailable()
        except Exception as e:
            logger.error(f"Failed to serve preview MIDI for score {score_id}: {str(e)}")
            return HttpResponse(status=500, content="Artifact could not be served.")


class ServeSourceAudioView(View):
    @session_view()
    def get(self, request, score_id):
        score = get_object_or_404(PDFFile, id=score_id)
        if score.source_type != PDFFile.SOURCE_TYPE_AUDIO:
            return HttpResponse(status=404, content="Source audio not available")

        temp_dir = settings.TEMP_STORAGE_DIR / str(score_id)
        audio_file = next(
            (
                candidate
                for candidate in temp_dir.glob("input.*")
                if candidate.suffix.lower() in {".mp3", ".wav", ".m4a"}
            ),
            None,
        )
        if not audio_file or not audio_file.exists():
            logger.error(f"Source audio file not found for score {score_id}")
            return HttpResponse(status=404, content="Source audio file not found")

        content_type, _ = mimetypes.guess_type(str(audio_file))
        try:
            return FileResponse(
                open(audio_file, "rb"),
                content_type=content_type or "audio/mpeg",
                as_attachment=False,
            )
        except FileNotFoundError:
            return unavailable()
        except Exception as e:
            logger.error(f"Failed to serve source audio for score {score_id}: {str(e)}")
            return HttpResponse(status=500, content="Artifact could not be served.")


class PDFListView(APIView):
    def get(self, request):
        from django.db.models import Q
        files = PDFFile.objects.filter(~Q(retention_kind="analysis") | (
            Q(deletion_pending=False) & (Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))))
        serializer = FileSerializer(files, many=True)
        response = Response(serializer.data)
        response["Cache-Control"] = "no-store"
        return response


class PDFFileDetailView(APIView):
    @session_view()
    def get(self, request, pk):
        try:
            score = PDFFile.objects.get(pk=pk)
            supplied_id = request.query_params.get("task_id")
            # Never query or disclose a task supplied by a caller. The stored association owns progress.
            task_status = score_task_status(score, AsyncResult)
            if supplied_id and supplied_id != score.analysis_task_id and task_status:
                task_status["info"]["task_id_status"] = "unassociated_ignored"
            serializer = FileSerializer(score)
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
                {"error": "Score could not be retrieved."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PDFDownloadView(APIView):
    @session_view()
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
    @session_view(mutating=True)
    def put(self, request, pk):
        pdf = get_object_or_404(PDFFile, pk=pk)
        serializer = FileSerializer(pdf, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
